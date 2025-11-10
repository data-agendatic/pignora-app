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
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
¡Bienvenido a Pignora! Esta herramienta te ayuda a estimar un valor de empeño combinando:

1.  **🏷️ Precios de Mercado:** Busca precios de artículos similares en eBay, Google Shopping y Encuentra24.
2.  **📉 Modelo de Depreciación:** Aplica ajustes por antigüedad y condición del artículo.
3.  **🤖 Ajuste con IA:** Ofrece una evaluación premium con justificación automática.
""")

# ================== FUNCIONES DE UTILIDAD ==================
TASAS_CAMBIO_A_USD = {"USD": 1.0, "EUR": 1.07, "GBP": 1.22}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen.upper(), 1)
    return precio * tasa

def construir_query(categoria: str, modelo: str) -> str:
    modelo = (modelo or "").strip()
    categoria = (categoria or "").strip()
    if not modelo and not categoria:
        return ""
    if not modelo:
        return categoria
    if not categoria or categoria.lower() in modelo.lower():
        return modelo
    return f"{modelo} {categoria}".strip()

# ================== eBAY SCRAPING ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.markdown(f"🔹 **eBay:** [{url}]({url})")

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            st.warning(f"⚠️ eBay devolvió código HTTP {resp.status_code}")
            return [], []

        matches = re.findall(r'\$\s?\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", "").strip())
            if 20 < val < 10000:
                precios.append(val)

        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})

        if not precios:
            st.info("ℹ️ No se detectaron precios claros en eBay para esta búsqueda.")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ eBay no disponible: {e}")
        return [], []

# ================== GOOGLE SHOPPING ==================
def buscar_google_shopping(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.google.com/search?tbm=shop&q={slug}"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.markdown(f"🔹 **Google Shopping:** [{url}]({url})")

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        matches = re.findall(r"\$\s?\d{2,5}(?:\.\d{2})?", text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", "").strip())
            if 10 < val < 10000:
                precios.append(val)

        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})

        if not precios:
            st.info("ℹ️ No se detectaron precios en Google Shopping (poca oferta o HTML cambió).")

        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Google Shopping no disponible: {e}")
        return [], []

# ================== ENCUENTRA24 (RSS) ==================
def buscar_encuentra24(query: str):
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []
    st.markdown(f"🔹 **Encuentra24:** [{url}]({url})")

    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            st.info("ℹ️ No se pudieron leer entradas RSS de Encuentra24.")
            return [], []

        palabras = [w.lower() for w in query.split() if len(w) > 2]

        for entry in feed.entries[:60]:
            titulo = entry.get("title", "")
            resumen = entry.get("summary", "")
            texto = f"{titulo} {resumen}".lower()
            if not any(p in texto for p in palabras):
                continue

            matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", f"{titulo} {resumen}")
            for m in matches:
                val = float(m)
                if 20 < val < 10000:
                    precios.append(val)
                    resultados.append({
                        "Fuente": "Encuentra24",
                        "Título": titulo[:60] + "...",
                        "Precio USD": val,
                        "Link": entry.link,
                    })

        if not precios:
            st.info("ℹ️ No se encontraron anuncios coincidentes en Encuentra24.")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Encuentra24 no disponible: {e}")
        return [], []

# ================== IA SEMÁNTICA (DEMO) ==================
def buscar_ia_semantica(query: str):
    if not client:
        st.warning("⚠️ IA semántica no disponible (falta API key).")
        return [], []

    ejemplos = [
        f"Vendo {query} usado, buen estado, $350.",
        f"{query} semi nuevo, caja incluida, 280 dólares.",
        f"Ofrezco {query} con garantía, 400 USD negociable.",
    ]
    texto = "\n".join(ejemplos)
    prompt = f"Extrae los precios en USD del siguiente texto:\n{texto}"

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Eres un extractor de precios."},
                      {"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50
        )
        out = resp.choices[0].message.content or ""
        nums = re.findall(r"\d+(?:\.\d+)?", out)
        precios = [float(x) for x in nums if 10 < float(x) < 10000]
        resultados = [{"Fuente": "IA Semántica", "Título": query, "Precio USD": p, "Link": "IA"} for p in precios]

        if not precios:
            st.info("ℹ️ La IA semántica no devolvió precios claros.")
        return precios, resultados

    except Exception as e:
        st.warning(f"IA semántica falló: {e}")
        return [], []

# ================== CÁLCULOS ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd:
        return None
    arr = np.array(precios_usd)
    mediana, promedio, minimo, maximo = np.median(arr), np.mean(arr), np.min(arr), np.max(arr)
    f_ant = max(0.30, 1 - 0.10 * antiguedad)
    f_cond = round(min(1.0, 0.4 + 0.6 * (condicion - 1) / 9), 2)
    f_riesgo = 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, minimo=minimo, maximo=maximo,
                valor_base=valor, factor_antiguedad=f_ant,
                factor_condicion=f_cond, factor_riesgo=f_riesgo)

def generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats):
    if not client:
        return "⚠️ IA no disponible: falta API key."

    prompt = f"""
Eres un tasador experto de casas de empeño.

Artículo: "{query}"
Descripción: "{descripcion}"
Precio original: {precio_original:.2f} USD
Antigüedad: {antiguedad} años
Condición: {condicion}/10
Valor base: {stats['valor_base']:.2f} USD
Devuelve: VALOR_RECOMENDADO_FINAL: <USD> - <justificación corta>.
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Eres un tasador experto de empeños."},
                      {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=80
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando IA: {e}"

# ================== INTERFAZ ==================
with st.sidebar:
    st.header("⚙️ Configuración del Artículo")
    categoria = st.selectbox("Tipo de artículo",
                             ["Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
                              "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro"])
    modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
    descripcion = st.text_area("Descripción", "Buen estado general, incluye accesorios.")
    precio_original = st.number_input("Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
    condicion = st.slider("Condición (1 = mala, 10 = excelente)", 1, 10, 7)
    usar_ia_premium = st.checkbox("Activar IA premium ($0.99)", value=False)

    st.subheader("🌐 Fuentes de Datos")
    usar_ebay = st.checkbox("eBay", value=True)
    usar_google = st.checkbox("Google Shopping", value=False)
    usar_encuentra = st.checkbox("Encuentra24 RSS", value=False)
    usar_ia_sem = st.checkbox("IA Semántica (texto libre)", value=False)

# ================== BOTÓN PERSONALIZADO Y PROCESO ==================
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
        box-shadow: 0px 4px 8px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background-color: #ff4b5c;
        transform: scale(1.02);
    }
    </style>
""", unsafe_allow_html=True)

if st.button("🚀 Calcular Estimación de Empeño", use_container_width=True):
    query = construir_query(categoria, modelo)
    if not query:
        st.error("❌ Especifica una categoría o modelo.")
        st.stop()

    st.subheader(f"🔍 Evaluando: '{query}'")

    precios_totales, resultados_totales = [], []

    if usar_ebay:
        p, r = buscar_ebay_publico(query); precios_totales += p; resultados_totales += r
    if usar_google:
        p, r = buscar_google_shopping(query); precios_totales += p; resultados_totales += r
    if usar_encuentra:
        p, r = buscar_encuentra24(query); precios_totales += p; resultados_totales += r
    if usar_ia_sem:
        p, r = buscar_ia_semantica(query); precios_totales += p; resultados_totales += r

    if not precios_totales:
        st.error("❌ No se encontraron precios en las fuentes seleccionadas.")
        st.stop()

    df = pd.DataFrame(resultados_totales)
    st.dataframe(df, use_container_width=True, hide_index=True)

    stats = calcular_valor_empeno(precios_totales, antiguedad, condicion)
    if not stats:
        st.error("❌ No se pudo calcular el valor.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Mediana", f"${stats['mediana']:.2f}")
    col2.metric("📊 Promedio", f"${stats['promedio']:.2f}")
    col3.metric("⬇️ Mínimo", f"${stats['minimo']:.2f}")
    col4.metric("⬆️ Máximo", f"${stats['maximo']:.2f}")

    st.info(f"Antigüedad: {stats['factor_antiguedad']:.2f} | "
            f"Condición: {stats['factor_condicion']:.2f} | "
            f"Margen Empeño: {stats['factor_riesgo']:.2f}")

    st.subheader(f"✅ Valor Base Sugerido: **${stats['valor_base']:.2f} USD**")

    df_precios = pd.DataFrame({'Precio (USD)': precios_totales})
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X('Precio (USD)', bin=alt.Bin(maxbins=20)),
        alt.Y('count()', title='Frecuencia'),
        tooltip=['Precio (USD)', 'count()']
    ).properties(title='Distribución de precios combinados')
    st.altair_chart(chart, use_container_width=True)

    if usar_ia_premium:
        comentario_ia = generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats)
        st.success(comentario_ia)
    st.caption("⚠️ Demo educativa. No sustituye una tasación profesional.")
