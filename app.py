"""
Plataforma de Problemas Urbanos
Stack: Python + Streamlit + SQLite + OpenStreetMap (via Folium)

- Cadastro: campos separados de endereço (CEP, rua, número, bairro, cidade, UF).
  O CEP preenche o endereço automaticamente (ViaCEP, com BrasilAPI de reserva).
  A latitude/longitude é obtida automaticamente pelo Nominatim (OpenStreetMap).
- Mapa: exibe os problemas já cadastrados.

Rodar com:  streamlit run app.py
"""

import html
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim
from streamlit_folium import st_folium

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
DB_PATH = Path(__file__).with_name("problemas.db")

TIPOS = {
    "Buraco": {"cor": "orange", "icone": "exclamation-triangle"},
    "Árvore caída": {"cor": "green", "icone": "tree"},
    "Alagamento": {"cor": "blue", "icone": "tint"},
    "Outro": {"cor": "gray", "icone": "info-sign"},
}
STATUS = ["Aberto", "Em andamento", "Resolvido"]
UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]
NOMES_UF = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}
ABREVIACOES = {
    "r": "Rua", "av": "Avenida", "al": "Alameda", "trav": "Travessa", "tv": "Travessa",
    "pç": "Praça", "pça": "Praça", "rod": "Rodovia", "est": "Estrada",
    "dr": "Doutor", "dra": "Doutora", "prof": "Professor", "profa": "Professora",
    "cel": "Coronel", "eng": "Engenheiro", "pres": "Presidente", "gen": "General",
    "cap": "Capitão", "ten": "Tenente", "pe": "Padre", "sto": "Santo", "sta": "Santa",
}
PREFIXOS_SEM_PONTO = {"r", "av", "al", "trav"}  # "R Sete de Setembro", "Av Brasil"
# Resultados do Nominatim que são áreas grandes demais para valer como "rua"
AREAS_GENERICAS = {
    "city", "town", "village", "municipality", "state", "country", "suburb", "neighbourhood",
    "quarter", "county", "region", "administrative", "city_district", "postcode", "hamlet",
}
COLUNAS_ENDERECO = ["cep", "rua", "numero", "bairro", "cidade", "estado"]

st.set_page_config(page_title="Problemas Urbanos", page_icon="📍", layout="wide")


# ----------------------------------------------------------------------
# Banco de dados (SQLite)
# ----------------------------------------------------------------------
def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def iniciar_db():
    with closing(conectar()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS problemas (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo         TEXT    NOT NULL,
                descricao    TEXT    NOT NULL,
                endereco     TEXT,
                latitude     REAL    NOT NULL,
                longitude    REAL    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'Aberto',
                criado_em    TEXT    NOT NULL
            )
            """
        )
        # Migração: adiciona as colunas de endereço em bancos criados antes
        existentes = {linha["name"] for linha in conn.execute("PRAGMA table_info(problemas)")}
        for coluna in COLUNAS_ENDERECO:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE problemas ADD COLUMN {coluna} TEXT")


def inserir_problema(tipo, descricao, cep, rua, numero, bairro, cidade, estado, endereco, lat, lon):
    with closing(conectar()) as conn, conn:
        conn.execute(
            """
            INSERT INTO problemas
                (tipo, descricao, cep, rua, numero, bairro, cidade, estado, endereco,
                 latitude, longitude, status, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Aberto', ?)
            """,
            (
                tipo, descricao, cep, rua, numero, bairro, cidade, estado, endereco,
                lat, lon, datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )


def listar_problemas() -> pd.DataFrame:
    with closing(conectar()) as conn:
        return pd.read_sql_query("SELECT * FROM problemas ORDER BY id DESC", conn)


def atualizar_status(problema_id: int, novo_status: str):
    with closing(conectar()) as conn, conn:
        conn.execute("UPDATE problemas SET status = ? WHERE id = ?", (novo_status, problema_id))


def excluir_problema(problema_id: int):
    with closing(conectar()) as conn, conn:
        conn.execute("DELETE FROM problemas WHERE id = ?", (problema_id,))


# ----------------------------------------------------------------------
# Endereço e geocodificação (Nominatim / OpenStreetMap)
# ----------------------------------------------------------------------
def formatar_endereco(rua, numero, bairro, cidade, estado, cep=""):
    logradouro = f"{rua}, {numero}" if numero else rua
    partes = [logradouro, bairro, f"{cidade} - {estado}"]
    if cep:
        partes.append(f"CEP {cep}")
    return ", ".join(p for p in partes if p)


def buscar_cep(cep: str):
    """
    Consulta o CEP no ViaCEP (base dos Correios); se o serviço falhar, tenta a BrasilAPI.
    Retorna {"rua", "bairro", "cidade", "estado"} ou None se o CEP não existir.
    Lança ValueError se o CEP for inválido e RuntimeError se nenhum serviço responder.
    """
    cep = "".join(ch for ch in cep if ch.isdigit())
    if len(cep) != 8:
        raise ValueError("CEP deve ter 8 dígitos")

    try:
        resp = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=8)
        resp.raise_for_status()
        dados = resp.json()
        if dados.get("erro"):
            return None
        return {
            "rua": dados.get("logradouro", ""),
            "bairro": dados.get("bairro", ""),
            "cidade": dados.get("localidade", ""),
            "estado": dados.get("uf", ""),
        }
    except (requests.RequestException, ValueError):
        pass  # tenta o serviço de reserva

    try:
        resp = requests.get(f"https://brasilapi.com.br/api/cep/v1/{cep}", timeout=8)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        dados = resp.json()
        return {
            "rua": dados.get("street") or "",
            "bairro": dados.get("neighborhood") or "",
            "cidade": dados.get("city") or "",
            "estado": dados.get("state") or "",
        }
    except (requests.RequestException, ValueError):
        raise RuntimeError("Serviços de CEP indisponíveis")


def normalizar_rua(rua: str) -> str:
    """Expande abreviações comuns (R., Av., Dr., Prof....) para o nome completo usado no OSM."""
    saida = []
    for i, palavra in enumerate(rua.split()):
        chave = palavra.rstrip(".").lower()
        if chave in ABREVIACOES and (palavra.endswith(".") or (i == 0 and chave in PREFIXOS_SEM_PONTO)):
            saida.append(ABREVIACOES[chave])
        else:
            saida.append(palavra)
    return " ".join(saida)


def geocodificar(rua, numero, bairro, cidade, estado, aceitar_aproximado=True):
    """
    Converte o endereço em coordenadas usando o Nominatim (OpenStreetMap).
    Tenta do mais específico ao mais geral e devolve (resultado, consultas_tentadas):
      resultado = (lat, lon, endereco_encontrado, precisao) ou None
      precisao  = "exata" (achou o número), "rua" (número não mapeado) ou "aproximada" (bairro/cidade)
    Lança GeocoderServiceError se o serviço estiver indisponível.
    """
    geolocator = Nominatim(user_agent="plataforma-problemas-urbanos", timeout=10)
    rua = normalizar_rua(rua)
    uf = NOMES_UF.get(estado, estado)  # o Nominatim entende melhor "São Paulo" do que "SP"
    pais = "Brasil"

    # (descrição, consulta, é_aproximada) - do mais específico para o mais geral
    consultas = []
    if numero:
        consultas.append((
            "rua + número (busca estruturada)",
            {"street": f"{numero} {rua}", "city": cidade, "state": uf, "country": pais},
            False,
        ))
    consultas.append((
        "rua (busca estruturada)",
        {"street": rua, "city": cidade, "state": uf, "country": pais},
        False,
    ))
    consultas.append(("rua (texto livre)", ", ".join([rua, cidade, uf, pais]), False))
    if bairro:
        consultas.append(("rua + bairro (texto livre)", ", ".join([rua, bairro, cidade, uf, pais]), False))
    if aceitar_aproximado:
        if bairro:
            consultas.append(("bairro (aproximada)", ", ".join([bairro, cidade, uf, pais]), True))
        consultas.append(("cidade (aproximada)", ", ".join([cidade, uf, pais]), True))

    tentadas = []
    for i, (descricao, consulta, aproximada) in enumerate(consultas):
        if i:
            time.sleep(1)  # Nominatim permite ~1 requisição por segundo
        texto = consulta if isinstance(consulta, str) else ", ".join(f"{k}={v}" for k, v in consulta.items())
        tentadas.append(f"{descricao}: {texto}")

        local = geolocator.geocode(
            consulta, country_codes="br", addressdetails=True, language="pt-BR"
        )
        if not local:
            continue

        tipo = local.raw.get("addresstype") or local.raw.get("type")
        if not aproximada and tipo in AREAS_GENERICAS:
            continue  # achou só a cidade/bairro, não a rua

        if aproximada:
            precisao = "aproximada"
        elif local.raw.get("address", {}).get("house_number"):
            precisao = "exata"
        else:
            precisao = "rua"
        return (local.latitude, local.longitude, local.address, precisao), tentadas

    return None, tentadas


# ----------------------------------------------------------------------
# Páginas
# ----------------------------------------------------------------------
def pagina_mapa():
    st.subheader("🗺️ Mapa de problemas")
    df = listar_problemas()

    if df.empty:
        st.info("Nenhum problema cadastrado ainda. Vá em **Cadastrar problema** para começar.")
        return

    # Filtros
    col1, col2 = st.columns(2)
    tipos_sel = col1.multiselect("Tipo", list(TIPOS), default=list(TIPOS))
    status_sel = col2.multiselect("Status", STATUS, default=["Aberto", "Em andamento"])
    df = df[df["tipo"].isin(tipos_sel) & df["status"].isin(status_sel)]

    # Métricas
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Exibidos", len(df))
    for coluna, tipo in zip((m2, m3, m4), ("Buraco", "Árvore caída", "Alagamento")):
        coluna.metric(tipo, int((df["tipo"] == tipo).sum()))

    if df.empty:
        st.warning("Nenhum problema com esses filtros.")
        return

    mapa = folium.Map(tiles="OpenStreetMap")
    cluster = MarkerCluster().add_to(mapa)

    for _, p in df.iterrows():
        estilo = TIPOS.get(p["tipo"], TIPOS["Outro"])
        popup = folium.Popup(
            f"<b>{html.escape(p['tipo'])}</b> (#{p['id']})<br>"
            f"{html.escape(p['descricao'])}<br>"
            f"<i>{html.escape(p['endereco'] or 'Sem endereço')}</i><br>"
            f"Status: <b>{html.escape(p['status'])}</b><br>"
            f"<small>{html.escape(p['criado_em'])}</small>",
            max_width=280,
        )
        folium.Marker(
            location=[p["latitude"], p["longitude"]],
            popup=popup,
            tooltip=f"{p['tipo']} - {p['status']}",
            icon=folium.Icon(color=estilo["cor"], icon=estilo["icone"], prefix="fa"),
        ).add_to(cluster)

    # Enquadra o mapa em todos os pontos
    mapa.fit_bounds(df[["latitude", "longitude"]].values.tolist(), max_zoom=16)

    # returned_objects=[] evita reruns a cada movimento do mapa
    st_folium(mapa, height=550, use_container_width=True, returned_objects=[])


def pagina_cadastro():
    st.subheader("📝 Cadastrar problema")
    st.caption("Preencha os dados e o endereço. A localização no mapa é encontrada automaticamente.")

    # Mensagem de sucesso do cadastro anterior (o formulário é reiniciado após salvar)
    if st.session_state.get("mensagem_sucesso"):
        st.success(st.session_state.pop("mensagem_sucesso"))
    if st.session_state.get("mensagem_aviso"):
        st.warning(st.session_state.pop("mensagem_aviso"))

    n = st.session_state.form_id  # muda a cada cadastro para limpar os campos

    # Busca por CEP fica fora do formulário: botões comuns não funcionam dentro de st.form
    c_cep, c_btn, _ = st.columns([2, 1, 4], vertical_alignment="bottom")
    cep = c_cep.text_input("CEP (opcional)", placeholder="00000-000", max_chars=9, key=f"cep_{n}")
    if c_btn.button("🔍 Buscar CEP", key=f"btn_cep_{n}"):
        try:
            dados = buscar_cep(cep)
        except ValueError:
            st.warning("Digite um CEP válido, com 8 números.")
        except RuntimeError:
            st.error("Não consegui consultar o CEP agora. Preencha o endereço manualmente ou tente de novo.")
        else:
            if not dados:
                st.warning("CEP não encontrado. Preencha o endereço manualmente.")
            else:
                # Preenche os campos do formulário (que ainda serão criados nesta execução)
                if dados["rua"]:
                    st.session_state[f"rua_{n}"] = dados["rua"]
                if dados["bairro"]:
                    st.session_state[f"bairro_{n}"] = dados["bairro"]
                st.session_state[f"cidade_{n}"] = dados["cidade"]
                if dados["estado"] in UFS:
                    st.session_state[f"estado_{n}"] = dados["estado"]
                st.success("Endereço preenchido! Informe o número e confira os dados.")

    with st.form(f"form_problema_{n}"):
        c1, c2 = st.columns([1, 2])
        tipo = c1.selectbox("Tipo de problema *", list(TIPOS), key=f"tipo_{n}")
        descricao = c2.text_area(
            "Descrição *",
            placeholder="Descreva o problema (tamanho, risco, ponto de referência...)",
            key=f"descricao_{n}",
        )

        st.markdown("**Endereço**")
        c3, c4 = st.columns([4, 1])
        rua = c3.text_input("Rua / Avenida *", key=f"rua_{n}")
        numero = c4.text_input("Número", key=f"numero_{n}")

        c5, c6, c7 = st.columns([2, 2, 1])
        bairro = c5.text_input("Bairro", key=f"bairro_{n}")
        cidade = c6.text_input("Cidade *", key=f"cidade_{n}")
        estado = c7.selectbox("UF *", UFS, index=None, placeholder="UF", key=f"estado_{n}")

        aproximado = st.checkbox(
            "Se a rua não for encontrada, usar a localização aproximada do bairro/cidade",
            value=True,
            key=f"aprox_{n}",
        )

        enviado = st.form_submit_button("Registrar problema", type="primary")

    if not enviado:
        return

    rua, numero, bairro, cidade = rua.strip(), numero.strip(), bairro.strip(), cidade.strip()

    if not (descricao.strip() and rua and cidade and estado):
        st.error("Preencha os campos obrigatórios: descrição, rua, cidade e UF.")
        return

    with st.spinner("Localizando o endereço no mapa..."):
        try:
            resultado, tentadas = geocodificar(rua, numero, bairro, cidade, estado, aproximado)
        except GeocoderServiceError:
            st.error("O serviço de localização está indisponível no momento. Tente novamente em instantes.")
            return

    if not resultado:
        st.error(
            "Não encontrei esse endereço no OpenStreetMap. Confira a grafia da rua e da cidade. "
            "Se a rua for nova ou pouco mapeada, marque a opção de localização aproximada."
        )
        with st.expander("Ver consultas tentadas"):
            for t in tentadas:
                st.code(t, language=None)
        return

    lat, lon, encontrado, precisao = resultado
    digitos = "".join(ch for ch in cep if ch.isdigit())
    cep_formatado = f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 8 else ""
    endereco = formatar_endereco(rua, numero, bairro, cidade, estado, cep_formatado)
    inserir_problema(
        tipo, descricao.strip(), cep_formatado, rua, numero, bairro, cidade, estado, endereco, lat, lon
    )

    st.session_state.mensagem_sucesso = f"Problema registrado! Local encontrado: {encontrado}"
    if precisao == "rua":
        st.session_state.mensagem_aviso = "O número não foi localizado no mapa; o ponto ficou posicionado na rua."
    elif precisao == "aproximada":
        st.session_state.mensagem_aviso = (
            "A rua não foi encontrada no OpenStreetMap; o ponto ficou na localização "
            "aproximada do bairro/cidade."
        )
    st.session_state.form_id += 1
    st.rerun()


def pagina_gestao():
    st.subheader("📋 Gerenciar registros")
    df = listar_problemas()

    if df.empty:
        st.info("Nenhum registro ainda.")
        return

    tabela = df[
        ["id", "tipo", "descricao", "cep", "rua", "numero", "bairro", "cidade", "estado",
         "status", "criado_em", "latitude", "longitude"]
    ].rename(
        columns={
            "id": "ID", "tipo": "Tipo", "descricao": "Descrição", "cep": "CEP", "rua": "Rua", "numero": "Nº",
            "bairro": "Bairro", "cidade": "Cidade", "estado": "UF", "status": "Status",
            "criado_em": "Criado em", "latitude": "Lat", "longitude": "Lon",
        }
    )
    st.dataframe(tabela, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Exportar CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name="problemas_urbanos.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("**Atualizar ou excluir um registro**")
    c1, c2, _ = st.columns([1, 2, 2])
    problema_id = c1.selectbox("ID", df["id"].tolist())
    atual = df.loc[df["id"] == problema_id, "status"].iloc[0]
    novo_status = c2.selectbox("Novo status", STATUS, index=STATUS.index(atual))

    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Atualizar status"):
        atualizar_status(problema_id, novo_status)
        st.rerun()
    if b2.button("Excluir"):
        excluir_problema(problema_id)
        st.rerun()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    iniciar_db()
    st.session_state.setdefault("form_id", 0)

    st.title("📍 Plataforma de Problemas Urbanos")
    pagina = st.sidebar.radio("Menu", ["Mapa", "Cadastrar problema", "Gerenciar"])

    if pagina == "Mapa":
        pagina_mapa()
    elif pagina == "Cadastrar problema":
        pagina_cadastro()
    else:
        pagina_gestao()

    st.sidebar.caption("Dados de mapa © colaboradores do OpenStreetMap")


if __name__ == "__main__":
    main()
