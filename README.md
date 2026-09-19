# 📍 Alerta Urbano

Plataforma web para **registrar e visualizar problemas urbanos** — como buracos, árvores caídas e alagamentos — em um **mapa interativo**.

Projeto desenvolvido no curso de IAG, com **Python, Streamlit, SQLite e OpenStreetMap**.

---

## ✨ Funcionalidades

- **Cadastro de problemas** com tipo (Buraco, Árvore caída, Alagamento ou Outro), descrição e endereço em campos separados: CEP, rua, número, bairro, cidade e UF.
- **Busca por CEP:** preenche rua, bairro, cidade e UF automaticamente.
- **Localização automática:** o endereço é convertido em latitude e longitude (geocodificação), sem precisar marcar o ponto manualmente.
- **Mapa interativo** com os problemas já cadastrados: ícones e cores por tipo, agrupamento de pontos próximos e popup com descrição, endereço, status e data.
- **Filtros** por tipo e status, com contadores por categoria.
- **Gerenciamento dos registros:** tabela completa, atualização de status (Aberto, Em andamento, Resolvido), exclusão e exportação para CSV.

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|---|---|
| Linguagem | Python |
| Interface | [Streamlit](https://streamlit.io/) |
| Banco de dados | SQLite |
| Mapa | [OpenStreetMap](https://www.openstreetmap.org/) via [Folium](https://python-visualization.github.io/folium/) e `streamlit-folium` |
| Geocodificação | [Nominatim](https://nominatim.org/) (OpenStreetMap) via `geopy` |
| Consulta de CEP | [ViaCEP](https://viacep.com.br/), com [BrasilAPI](https://brasilapi.com.br/) como reserva |

---

## 🚀 Como executar

**Pré-requisitos:** Python 3.9 ou superior e acesso à internet (mapa, CEP e geocodificação).

```bash
# 1. Clone o repositório
git clone <URL-DO-REPOSITORIO>
cd alerta-urbano

# 2. (Opcional) Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Execute
streamlit run app.py
```

O navegador abrirá em `http://localhost:8501`. O banco `problemas.db` é criado automaticamente na primeira execução.

---

## 📖 Como usar

1. Abra **Cadastrar problema**.
2. (Opcional) Digite o **CEP** e clique em **Buscar CEP** para preencher o endereço.
3. Informe o tipo, a descrição, a rua, o número, a cidade e a UF, e clique em **Registrar problema**.
4. Vá até a aba **Mapa** para ver os problemas pontuados, filtrar por tipo ou status e clicar nos marcadores para ver os detalhes.
5. Na aba **Gerenciar**, atualize o status, exclua registros ou exporte os dados em CSV.

---

## 🗂️ Estrutura do projeto

```
alerta-urbano/
├── app.py             # Aplicação Streamlit (páginas, banco, CEP e geocodificação)
├── requirements.txt   # Dependências
├── README.md
└── problemas.db       # Banco SQLite (gerado automaticamente, não versionado)
```

## 🗄️ Modelo de dados

Tabela `problemas`:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER (PK) | Identificador |
| `tipo` | TEXT | Buraco, Árvore caída, Alagamento ou Outro |
| `descricao` | TEXT | Descrição do problema |
| `cep`, `rua`, `numero`, `bairro`, `cidade`, `estado` | TEXT | Endereço em campos separados |
| `endereco` | TEXT | Endereço completo formatado |
| `latitude`, `longitude` | REAL | Coordenadas obtidas pela geocodificação |
| `status` | TEXT | Aberto, Em andamento ou Resolvido |
| `criado_em` | TEXT | Data e hora do cadastro |

---

## ⚠️ Observações

- **Precisão da localização:** a geocodificação depende da cobertura do OpenStreetMap. Quando o número não está mapeado, o ponto fica na rua. Se a rua também não for encontrada, o app pode usar a localização aproximada do bairro ou da cidade (opção marcada por padrão no formulário), e avisa quando isso acontece.
- **Limites dos serviços gratuitos:** o Nominatim permite cerca de uma consulta por segundo, então o cadastro pode levar alguns segundos. O app já respeita esse intervalo.
- **Dados de mapa** © colaboradores do OpenStreetMap.

---

## 🔭 Próximos passos

- Anexar fotos aos registros.
- Classificar o tipo do problema automaticamente a partir da descrição, usando um LLM.
- Mapa de calor das áreas mais críticas.
- Autenticação e perfis de usuário (cidadão e administrador).
