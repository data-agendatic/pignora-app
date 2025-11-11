import re, requests, numpy as np, pandas as pd, feedparser, altair as alt, streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

# ================== CONFIGURACIÓN INICIAL ==================
OPENAI_API_KEY = None  # opcional, solo si tienes una
METALSDEV_API_KEY = "HD5SVRDTPC4P0UWJ0ATH699WJ0ATH"  # tu API key de Metals.dev
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador Multiactivo", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador Multiactivo")

st.markdown("""
Evalúa distintos tipos de activos o simula operaciones financieras:

- **💻 Electrónica:** busca precios de mercado (eBay, Google Shopping, Encuentra24).  
- **🟡 Prendas de Oro:** estima por peso y pureza (precio real en tiempo).  
- **🌐 Activos Digitales:** valora dominios o redes sociales.  
- **💳 Custodia / PayPal:** simula operaciones Fintech seguras.
---
""")

# ================== FUNCIONES DE UTILIDAD ==================
def construir_query(categoria: str, modelo: str) -> str:
    modelo, categoria = (modelo or "").strip(), (categoria or "").strip()
    if not modelo and not categoria: return ""
    if not modelo: return categoria
    if not categoria or categoria.lower() in modelo.lower(): return modelo
    return f"{modelo} {categoria}".strip()

# ================== SCRAPING - ELECTRÓNICA ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []
    st.markdown(f"🔹 **eBay:** [{url}]({url})")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        matches = re.findall(r'\$\s?\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 20 < val < 10000: precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except: return [], []

def buscar_google_shopping(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.google.com/search?tbm=shop&q={slug}"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []
    st.markdown(f"🔹 **Google Shopping:** [{url}]({url})")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
        matches = re.findall(r"\$\s?\d{2,5}(?:\.\d{2})?", text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 10 < val < 10000: precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except: return [], []

def buscar_encuentra24(query: str):
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []
    st.markdown(f"🔹 **Encuentra24:** [{url}]({url})")
    try:
        feed = feedparser.parse(url)
        palabras = [w.lower() for w in query.split() if len(w) > 2]
        for entry in feed.entries[:60]:
            texto = f"{entry.get('title','')} {entry.get('summary','')}".lower()
            if not any(p in texto for p in palabras): continue
            matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", texto)
            for m in matches:
                val = float(m)
                if 20 < val < 10000:
                    precios.append(val)
                    resultados.append({
                        "Fuente": "Encuentra24",
                        "Título": entry.title[:60]+"...",
                        "Precio USD": val,
                        "Link": entry.link
                    })
        return precios, resultados
    except: return [], []

# ================== ORO (API METALS.DEV) ==================
def obtener_precio_oro_por_gramo(api_key: str) -> float:
    """Consulta el precio actual del oro en USD/gramo usando Metals.dev"""
    try:
        url = f"https://api.metals.dev/v1/latest?api_key={api_key}&currency=USD&unit=toz"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if "metals" in data and "XAU" in data["metals"]:
            precio_onza = data["metals"]["XAU"]["price"]
            precio_gramo = precio_onza / 31.1035
            return round(precio_gramo, 2)
        else:
            st.warning("⚠️ API Metals.dev sin datos válidos, usando 75 USD/g.")
            return 75.0
    except Exception as e:
        st.warning(f"⚠️ Error consultando API Metals.dev: {e}")
        return 75.0

def estimar_oro(peso_gramos: float, pureza: int, api_key: str):
    precio_oro_puro = obtener_precio_oro_por_gramo(api_key)
    factor_pureza = pureza / 24
    valor_bruto = peso_gramos * precio_oro_puro * factor_pureza
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2), precio_oro_puro

# ================== FINTECH ==================
def simular_escrow(monto: float, dias: int):
    comision = monto * 0.035
    return monto, comision, monto - comision, dias

def simular_paypal_to_ach(monto: float):
    comision = monto * 0.08
    return monto, comision, monto - comision, "24 horas"

# ================== CÁLCULO BASE ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd: return None
    arr = np.array(precios_usd)
    mediana, promedio = np.median(arr), np.mean(arr)
    f_ant, f_cond, f_riesgo = max(0.3, 1 - 0.1 * antiguedad), round(min(1, 0.4 + 0.6 * (condicion - 1) / 9), 2), 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, valor=valor)

# ================== ESTILO BOTÓN ROJO ==================
st.markdown("""
<style>
div.stButton > button:first-child {
    background-color: #e63946;
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 6px;
    height: 3em;
    width: 100%;
    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    transition: all 0.3s ease;
}
div.stButton > button:first-child:hover {
    background-color: #ff4b5c;
    transform: scale(1.02);
}
</style>
""", unsafe_allow_html=True)

# ================== INTERFAZ PRINCIPAL ==================
tipo = st.radio("Selecciona una opción:",
                ["💻 Electrónica", "🟡 Prendas de Oro", "🌐 Activos Digitales", "💳 Custodia / PayPal"],
                horizontal=True)

if tipo == "💻 Electrónica":
    with st.sidebar:
        categoria = st.selectbox("Tipo de artículo", ["Laptop", "iPhone", "Consola", "Televisor", "Otro"])
        modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
        antiguedad = st.slider("Antigüedad (años)", 0, 10, 3)
        condicion = st.slider("Condición (1-10)", 1, 10, 7)
        usar_ebay = st.checkbox("eBay", True)
        usar_google = st.checkbox("Google Shopping", False)
        usar_encuentra = st.checkbox("Encuentra24", False)

elif tipo == "🟡 Prendas de Oro":
    with st.sidebar:
        peso = st.number_input("Peso (gramos)", 0.1, 500.0, 10.0, 0.1)
        pureza = st.selectbox("Pureza (K)", [10, 14, 18, 22, 24], index=2)

elif tipo == "🌐 Activos Digitales":
    with st.sidebar:
        url = st.text_input("Dominio o cuenta", "https://tusitio.com")

elif tipo == "💳 Custodia / PayPal":
    with st.sidebar:
        monto = st.number_input("Monto (USD)", 10.0, 10000.0, 500.0, 10.0)
        dias = st.slider("Días en Escrow", 1, 30, 7)

# ================== BOTÓN PRINCIPAL ==================
if st.button("🚀 Ejecutar / Calcular", use_container_width=True):

    if tipo == "🟡 Prendas de Oro":
        bruto, empeño, precio_gramo = estimar_oro(peso, pureza, METALSDEV_API_KEY)
        st.metric("💰 Precio actual del oro (g)", f"${precio_gramo:.2f}")
        st.metric("💎 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor empeño sugerido", f"${empeño:,.2f}")
