import os
import re
import time
import requests
import numpy as np
import pandas as pd
import feedparser
from bs4 import BeautifulSoup
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import altair as alt

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador de Empeño", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador Multiactivo")

st.markdown("""
¡Bienvenido a **Pignora**!  
Selecciona el tipo de activo para calcular su valor estimado de empeño:

- **💻 Electrónica:** busca precios en eBay, Google Shopping y Encuentra24.  
- **🟡 Prendas de Oro:** calcula por peso y pureza.  
- **🌐 Activos Digitales:** estima valor de dominios, webs o redes sociales.  
""")

# ================== FUNCIONES DE UTILIDAD ==================
TASAS_CAMBIO_A_USD = {"USD": 1.0, "EUR": 1.07, "GBP": 1.22}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    return precio * TASAS_CAMBIO_A_USD.get(moneda_origen.upper(), 1)

def construir_query(categoria: str, modelo: str) -> str:
    modelo, categoria = (modelo or "").strip(), (categoria or "").strip()
    if not modelo and not categoria: return ""
    if not modelo: return categoria
    if not categoria or categoria.lower() in modelo.lower(): return modelo
    return f"{modelo} {categoria}".strip()

# ================== ESTIMADOR DE ORO ==================
def estimar_oro(peso_gramos: float, pureza: int):
    precio_oro_puro = 75.0  # USD/gramo
    factor_pureza = pureza / 24
    valor_bruto = peso_gramos * precio_oro_puro * factor_pureza
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2)

# ================== ESTIMADOR DE ACTIVOS DIGITALES ==================
def estimar_activo_digital(url: str):
    """Consulta valor estimado de una web o dominio vía siteprice.org"""
    headers = {"User-Agent": "Mozilla/5.0"}
    site = url.replace("https://", "").replace("http://", "").split("/")[0]
    check_url = f"https://www.siteprice.org/website-worth/{site}"
    st.markdown(f"🔹 **Valorando dominio:** [{check_url}]({check_url})")

    try:
        resp = requests.get(check_url, headers=headers, timeout=10)
        resp.raise_for_status()
        match = re.search(r"\$[0-9,]+", resp.text)
        if match:
            val = float(match.group(0).replace("$", "").replace(",", ""))
            valor_empeno = val * 0.5
            return val, valor_empeno
        else:
            st.info("ℹ️ No se detectó valoración disponible para ese dominio.")
            return None, None
    except Exception as e:
        st.warning(f"⚠️ Error estimando activo digital: {e}")
        return None, None

# ================== SCRAPING / IA ELECTRÓNICA ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200: return [], []
        matches = re.findall(r'\$\s?\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 20 < val < 10000: precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception:
        return [], []

def buscar_google_shopping(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.google.com/search?tbm=shop&q={slug}"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        matches = re.findall(r"\$\s?\d{2,5}(?:\.\d{2})?", soup.get_text())
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 10 < val < 10000: precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception:
        return [], []

def buscar_encuentra24(query: str):
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []
    try:
        feed = feedparser.parse(url)
        palabras = [w.lower() for w in query.split() if len(w) > 2]
        for entry in feed.entries[:60]:
            texto = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
            if not any(p in texto for p in palabras): continue
            matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", texto)
            for m in matches:
                val = float(m)
                if 20 < val < 10000:
                    precios.append(val)
                    resultados.append({
                        "Fuente": "Encuentra24", "Título": entry.title[:60] + "...",
                        "Precio USD": val, "Link": entry.link
                    })
        return precios, resultados
    except Exception:
        return [], []

# ================== CÁLCULO BASE ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd: return None
    arr = np.array(precios_usd)
    mediana, promedio, minimo, maximo = np.median(arr), np.mean(arr), np.min(arr), np.max(arr)
    f_ant = max(0.30, 1 - 0.10 * antiguedad)
    f_cond = round(min(1.0, 0.4 + 0.6 * (condicion - 1) / 9), 2)
    f_riesgo = 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, minimo=minimo, maximo=maximo,
                valor_base=valor, factor_antiguedad=f_ant, factor_condicion=f_cond, factor_riesgo=f_riesgo)

# ================== INTERFAZ ==================
tipo_activo = st.radio("Selecciona el tipo de activo:",
                       ["💻 Electrónica", "🟡 Prendas de Oro", "🌐 Activos Digitales"],
                       horizontal=True)

if tipo_activo == "💻 Electrónica":
    with st.sidebar:
        st.header("⚙️ Configuración del Artículo")
        categoria = st.selectbox("Tipo de artículo",
                                 ["Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
                                  "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro"])
        modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
        descripcion = st.text_area("Descripción", "Buen estado general, incluye accesorios.")
        precio_original = st.number_input("Precio original (USD)", 10.0, step=10.0)
        antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
        condicion = st.slider("Condición (1 = mala, 10 = excelente)", 1, 10, 7)
        usar_ebay = st.checkbox("eBay", value=True)
        usar_google = st.checkbox("Google Shopping", value=False)
        usar_encuentra = st.checkbox("Encuentra24 RSS", value=False)

elif tipo_activo == "🟡 Prendas de Oro":
    with st.sidebar:
        st.header("⚙️ Datos de la Prenda")
        peso_gramos = st.number_input("Peso (gramos)", 0.1, 500.0, 10.0, 0.1)
        pureza = st.selectbox("Pureza (quilates)", [10, 14, 18, 22, 24], index=2)

elif tipo_activo == "🌐 Activos Digitales":
    with st.sidebar:
        st.header("⚙️ Activo Digital")
        url = st.text_input("URL del dominio / red social", "https://tusitio.com")

# ================== BOTÓN PRINCIPAL ==================
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

# ================== PROCESAMIENTO ==================
if st.button("🚀 Calcular Estimación de Empeño", use_container_width=True):

    # --- ELECTRÓNICA ---
    if tipo_activo == "💻 Electrónica":
        query = construir_query(categoria, modelo)
        precios, resultados = [], []
        if usar_ebay: p, r = buscar_ebay_publico(query); precios += p; resultados += r
        if usar_google: p, r = buscar_google_shopping(query); precios += p; resultados += r
        if usar_encuentra: p, r = buscar_encuentra24(query); precios += p; resultados += r

        if not precios:
            st.error("❌ No se encontraron precios en las fuentes seleccionadas.")
            st.stop()

        df = pd.DataFrame(resultados)
        st.dataframe(df, use_container_width=True, hide_index=True)
        stats = calcular_valor_empeno(precios, antiguedad, condicion)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 Mediana", f"${stats['mediana']:.2f}")
        col2.metric("📊 Promedio", f"${stats['promedio']:.2f}")
        col3.metric("⬇️ Mínimo", f"${stats['minimo']:.2f}")
        col4.metric("⬆️ Máximo", f"${stats['maximo']:.2f}")
        st.info(f"Antigüedad: {stats['factor_antiguedad']:.2f} | Condición: {stats['factor_condicion']:.2f}")
        st.subheader(f"✅ Valor Base Sugerido: **${stats['valor_base']:.2f} USD**")

        chart = alt.Chart(pd.DataFrame({'Precio (USD)': precios})).mark_bar().encode(
            alt.X('Precio (USD)', bin=alt.Bin(maxbins=20)),
            alt.Y('count()', title='Frecuencia'),
            tooltip=['Precio (USD)', 'count()']
        )
        st.altair_chart(chart, use_container_width=True)

    # --- ORO ---
    elif tipo_activo == "🟡 Prendas de Oro":
        bruto, empeno = estimar_oro(peso_gramos, pureza)
        st.subheader("🟡 Estimación de Prenda de Oro")
        st.metric("💰 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor de empeño sugerido", f"${empeno:,.2f}")
        st.caption(f"Cálculo basado en {pureza}K y $75.00/g de oro puro.")

    # --- ACTIVO DIGITAL ---
    elif tipo_activo == "🌐 Activos Digitales":
        bruto, empeno = estimar_activo_digital(url)
        if bruto:
            st.subheader("🌐 Estimación de Activo Digital")
            st.metric("💻 Valor estimado del sitio", f"${bruto:,.2f}")
            st.metric("💵 Valor de empeño sugerido", f"${empeno:,.2f}")
            st.caption("Fuente: siteprice.org / estimación de valor web aproximado.")

            # ================== ESCROW ==================
            st.markdown("---")
            st.subheader("💼 Simulador de Custodia (Escrow)")
            monto_escrow = st.number_input("Monto a custodiar (USD)", min_value=10.0, step=10.0, value=empeno)
            dias_escrow = st.slider("Días de retención", min_value=1, max_value=30, value=7)

            def simular_escrow(monto, dias, comision_pct=3.5):
                comision = monto * comision_pct / 100
                neto = monto - comision
                return {"monto": monto, "comision": comision, "neto": neto, "dias": dias}

            if st.button("🧾 Calcular Custodia Simulada"):
                datos = simular_escrow(monto_escrow, dias_escrow)
                st.success(f"""
                💰 **Monto en custodia:** ${datos['monto']:.2f}  
                💸 **Comisión (3.5%)**: ${datos['comision']:.2f}  
                🏦 **Monto liberado:** ${datos['neto']:.2f}  
                ⏳ **Retención:** {datos['dias']} días
                """)
                df = pd.DataFrame({
                    "Concepto": ["Comisión", "Monto liberado"],
                    "Valor": [datos['comision'], datos['neto']]
                })
                chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
                    theta="Valor", color="Concepto", tooltip=["Concepto", "Valor"]
                )
                st.altair_chart(chart, use_container_width=True)

            # ================== PAYPAL -> ACH ==================
            st.markdown("---")
            st.subheader("💳 Simulador PayPal → ACH")
            monto_paypal = st.number_input("Monto a convertir desde PayPal (USD)", min_value=10.0, step=10.0, value=empeno)
            def simular_paypal_to_ach(monto, comision_pct=8.0):
                comision = monto * comision_pct / 100
                neto = monto - comision
                return {"deposito": monto, "comision": comision, "neto": neto}

            if st.button("🏦 Simular Retiro ACH"):
                datos = simular_paypal_to_ach(monto_paypal)
                st.success(f"""
                📥 **Depósito PayPal:** ${datos['deposito']:.2f}  
                💸 **Comisión (8%)**: ${datos['comision']:.2f}  
                🏦 **Transferencia ACH neta:** ${datos['neto']:.2f}  
                ⏱️ **Tiempo estimado:** 24 horas
                """)
                df = pd.DataFrame({
                    "Concepto": ["Comisión", "Transferencia neta"],
                    "Valor": [datos['comision'], datos['neto']]
                })
                chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
                    theta="Valor", color="Concepto", tooltip=["Concepto", "Valor"]
                )
                st.altair_chart(chart, use_container_width=True)
        else:
            st.error("No se pudo obtener un valor estimado para este dominio.")
