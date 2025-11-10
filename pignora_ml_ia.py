import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd
import altair as alt
import re
import feedparser
import time
from bs4 import BeautifulSoup

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
    base = categoria if categoria != "Otro" else ""
    texto = (base + " " + modelo).strip()
    return texto if texto else modelo


# ================== eBAY SCRAPER ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.write(f"🔹 eBay: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        matches = re.findall(r'\$\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", ""))
            if 20 < val < 5000:
                precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception as e:
        st.warning(f"eBay no disponible: {e}")
        return [], []


# ================== GOOGLE SHOPPING ==================
def buscar_google_shopping(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.google.com/search?tbm=shop&q={slug}"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.write(f"🔹 Google Shopping: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        price_tags = re.findall(r"\$\s?\d+(?:\.\d{2})?", soup.get_text())
        for t in price_tags:
            val = float(t.replace("$", "").strip())
            if 10 < val < 10000:
                precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception as e:
        st.warning(f"Google Shopping no disponible: {e}")
        return [], []


# ================== ENCUENTRA24 (RSS FEED) ==================
def buscar_encuentra24(query: str):
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []
    st.write(f"🔹 Encuentra24: {url}")
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:30]:
            if query.lower() in entry.title.lower():
                matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", entry.title)
                for m in matches:
                    val = float(m)
                    if 20 < val < 5000:
                        precios.append(val)
                        resultados.append({
                            "Fuente": "Encuentra24",
                            "Título": entry.title[:60] + "...",
                            "Precio USD": val,
                            "Link": entry.link,
                        })
        return precios, resultados
    except Exception as e:
        st.warning(f"Encuentra24 no disponible: {e}")
        return [], []


# ================== IA SEMÁNTICA ==================
def buscar_ia_semantica(query: str):
    """Usa OpenAI para inferir precios desde texto de listados sin estructura."""
    if not client:
        st.warning("IA no disponible (falta API key).")
        return [], []
    ejemplos = [
        f"Vendo {query} usado, buen estado, $350.",
        f"{query} semi nuevo, caja incluida, 280 dólares.",
        f"Ofrezco {query} con garantía, 400 USD negociable.",
    ]
    texto = "\n".join(ejemplos)
    prompt = f"Extrae los precios numéricos en USD del siguiente texto:\n{texto}"
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Eres un extractor de precios."},
                      {"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50
        )
        output = resp.choices[0].message.content
        precios = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", output)]
        resultados = [{"Fuente": "IA Semántica", "Título": query, "Precio USD": p, "Link": "IA"} for p in precios]
        return precios, resultados
    except Exception as e:
        st.warning(f"IA Semántica falló: {e}")
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

# ================== PROCESO ==================
if st.button("🚀 Calcular Estimación de Empeño", use_container_width=True):
    query = construir_query(categoria, modelo)
    st.subheader(f"🔍 Evaluando: '{query}'")

    precios_totales, resultados_totales = [], []

    if usar_ebay:
        p, r = buscar_ebay_publico(query)
        precios_totales += p; resultados_totales += r
    if usar_google:
        p, r = buscar_google_shopping(query)
        precios_totales += p; resultados_totales += r
    if usar_encuentra:
        p, r = buscar_encuentra24(query)
        precios_totales += p; resultados_totales += r
    if usar_ia_sem:
        p, r = buscar_ia_semantica(query)
        precios_totales += p; resultados_totales += r

    if not precios_totales:
        st.error("❌ No se encontraron precios en las fuentes seleccionadas.")
        st.stop()

    df = pd.DataFrame(resultados_totales)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    stats = calcular_valor_empeno(precios_totales, antiguedad, condicion)
    if not stats:
        st.error("No se pudo calcular el valor de empeño.")
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
        prompt = f"""
        Sugiere un valor de empeño para '{query}' basado en:
        Mediana {stats['mediana']:.2f}, promedio {stats['promedio']:.2f}, condición {condicion}/10,
        antigüedad {antiguedad} años, y valor base {stats['valor_base']:.2f}.
        Formato:
        VALOR_RECOMENDADO_FINAL: <USD> - <justificación corta>.
        """
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Eres un tasador experto de empeños."},
                          {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=80
            )
            salida = resp.choices[0].message.content.strip()
            st.success(salida)
        except Exception as e:
            st.warning(f"Error en IA Premium: {e}")

    st.caption("⚠️ Demo educativa. No sustituye una tasación profesional.")
