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
TASAS_CAMBIO_A_USD = {
    "USD": 1.0,
    "EUR": 1.07,
    "GBP": 1.22,
}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen.upper(), 1)
    return precio * tasa

def construir_query(categoria: str, modelo: str) -> str:
    """
    Construye una query razonable para buscadores y feeds.
    Prioriza el modelo y añade la categoría solo si aporta contexto.
    """
    modelo = (modelo or "").strip()
    categoria = (categoria or "").strip()

    if not modelo and not categoria:
        return ""

    if not modelo:
        return categoria

    if not categoria or categoria.lower() in modelo.lower():
        return modelo

    return f"{modelo} {categoria}".strip()


# ================== eBAY (SCRAPING PÚBLICO) ==================
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
            resultados.append({
                "Fuente": "eBay",
                "Título": query,
                "Precio USD": p,
                "Link": url
            })

        if not precios:
            st.info("ℹ️ No se detectaron precios claros en eBay para esta búsqueda.")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ eBay no disponible: {e}")
        return [], []


# ================== GOOGLE SHOPPING (SERP PÚBLICA) ==================
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

        # Buscamos patrones tipo $123 o $1,234.56
        matches = re.findall(r"\$\s?\d{2,5}(?:\.\d{2})?", text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", "").strip())
            if 10 < val < 10000:
                precios.append(val)

        for p in precios[:10]:
            resultados.append({
                "Fuente": "Google Shopping",
                "Título": query,
                "Precio USD": p,
                "Link": url
            })

        if not precios:
            st.info("ℹ️ No se detectaron precios en Google Shopping (poca oferta o HTML cambió).")

        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Google Shopping no disponible: {e}")
        return [], []


# ================== ENCUENTRA24 (RSS) ==================
def buscar_encuentra24(query: str):
    """
    Usa el feed RSS general y filtra por palabras clave del query.
    """
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
            st.info("ℹ️ No se encontraron anuncios coincidentes con el artículo en Encuentra24.")

        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Encuentra24 no disponible: {e}")
        return [], []


# ================== IA SEMÁNTICA (DEMO) ==================
def buscar_ia_semantica(query: str):
    """
    Demo: inventa 2-3 precios plausibles usando IA a partir del nombre del artículo.
    Sirve como fuente adicional simulada.
    """
    if not client:
        st.warning("⚠️ IA semántica no disponible (falta OPENAI_API_KEY).")
        return [], []

    ejemplos = [
        f"Vendo {query} usado, buen estado, $350.",
        f"{query} semi nuevo, caja incluida, 280 dólares.",
        f"Ofrezco {query} con garantía, 400 USD negociable.",
    ]
    texto = "\n".join(ejemplos)

    prompt = f"""
A partir del siguiente texto con anuncios, extrae SOLO los precios en USD como números:
{texto}

Responde en este formato exacto:
PRECIOS: 350, 280, 400
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un extractor de precios muy preciso."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=50,
        )
        out = resp.choices[0].message.content or ""
        nums = re.findall(r"\d+(?:\.\d+)?", out)
        precios = [float(x) for x in nums if 10 < float(x) < 10000]

        resultados = [{
            "Fuente": "IA Semántica",
            "Título": query,
            "Precio USD": p,
            "Link": "IA"
        } for p in precios]

        if not precios:
            st.info("ℹ️ La IA semántica no devolvió precios claros.")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ IA semántica falló: {e}")
        return [], []


# ================== CÁLCULO DE VALOR DE EMPEÑO ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd:
        return None

    arr = np.array(precios_usd)
    mediana = float(np.median(arr))
    promedio = float(np.mean(arr))
    minimo = float(np.min(arr))
    maximo = float(np.max(arr))

    factor_antiguedad = max(0.30, 1 - 0.10 * antiguedad)
    factor_condicion = 0.4 + (0.6 * (condicion - 1) / 9)
    factor_condicion = round(min(1.0, factor_condicion), 2)
    factor_riesgo_ganancia = 0.55

    valor_base = mediana * factor_antiguedad * factor_condicion * factor_riesgo_ganancia

    return {
        "mediana": mediana,
        "promedio": promedio,
        "minimo": minimo,
        "maximo": maximo,
        "valor_base": valor_base,
        "factor_antiguedad": factor_antiguedad,
        "factor_condicion": factor_condicion,
        "factor_riesgo_ganancia": factor_riesgo_ganancia,
    }


def generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats):
    if not client:
        return "⚠️ IA no disponible: falta OPENAI_API_KEY."

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Artículo: "{query}"
Descripción: "{descripcion}"
Precio original (nuevo): {precio_original:.2f} USD
Antigüedad: {antiguedad} años
Condición: {condicion}/10

Datos de mercado:
- Mediana: {stats['mediana']:.2f} USD
- Promedio: {stats['promedio']:.2f} USD
- Rango: {stats['minimo']:.2f} - {stats['maximo']:.2f} USD
- Valor base sugerido: {stats['valor_base']:.2f} USD

Responde en este formato EXACTO:
VALOR_RECOMENDADO_FINAL: <número en USD> - <justificación breve en máximo 20 palabras>.
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un tasador de empeños equilibrado y realista."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}"


# ================== INTERFAZ DE USUARIO ==================
with st.sidebar:
    st.header("⚙️ Configuración del Artículo")
    categoria = st.selectbox(
        "Tipo de artículo",
        ["Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
         "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro"],
    )
    modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
    descripcion = st.text_area("Descripción", "Buen estado general, incluye accesorios.")
    precio_original = st.number_input("Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
    condicion = st.slider("Condición (1 = mala, 10 = excelente)", 1, 10, 7)

    st.subheader("🌐 Fuentes de Datos")
    usar_ebay = st.checkbox("eBay", value=True)
    usar_google = st.checkbox("Google Shopping", value=False)
    usar_encuentra = st.checkbox("Encuentra24 RSS", value=False)
    usar_ia_sem = st.checkbox("IA Semántica (texto libre)", value=False)

    st.subheader("💡 IA Premium")
    usar_ia_premium = st.checkbox("Activar IA premium (simula $0.99)", value=False)

st.markdown("---")

# ================== FLUJO PRINCIPAL ==================
if st.button("🚀 Calcular Estimación de Empeño", use_container_width=True):
    query = construir_query(categoria, modelo)

    if not query:
        st.error("❌ Especifica al menos una categoría o modelo para buscar.")
        st.stop()

    st.subheader(f"🔍 Evaluando: **'{query}'**")

    precios_totales = []
    resultados_totales = []

    # eBay
    if usar_ebay:
        p, r = buscar_ebay_publico(query)
        precios_totales += p
        resultados_totales += r

    # Google Shopping
    if usar_google:
        p, r = buscar_google_shopping(query)
        precios_totales += p
        resultados_totales += r

    # Encuentra24
    if usar_encuentra:
        p, r = buscar_encuentra24(query)
        precios_totales += p
        resultados_totales += r

    # IA Semántica
    if usar_ia_sem:
        p, r = buscar_ia_semantica(query)
        precios_totales += p
        resultados_totales += r

    if not precios_totales:
        st.error("❌ No se encontraron precios en las fuentes seleccionadas.")
        st.stop()

    # Tabla de resultados combinados
    df = pd.DataFrame(resultados_totales)
    st.markdown("### 📊 Resultados de mercado combinados")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Cálculo de valor de empeño
    stats = calcular_valor_empeno(precios_totales, antiguedad, condicion)
    if stats is None:
        st.error("❌ No se pudo calcular el valor de empeño.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Mediana (USD)", f"${stats['mediana']:.2f}")
    col2.metric("📊 Promedio (USD)", f"${stats['promedio']:.2f}")
    col3.metric("⬇️ Mínimo (USD)", f"${stats['minimo']:.2f}")
    col4.metric("⬆️ Máximo (USD)", f"${stats['maximo']:.2f}")

    st.markdown("#### Factores de ajuste")
    st.info(
        f"Antigüedad: **{stats['factor_antiguedad']:.2f}** | "
        f"Condición: **{stats['factor_condicion']:.2f}** | "
        f"Factor empeño (riesgo/ganancia): **{stats['factor_riesgo_ganancia']:.2f}**"
    )

    st.subheader(f"✅ Valor Base Sugerido de Empeño: **${stats['valor_base']:.2f} USD**")

    # Histograma
    df_precios = pd.DataFrame({"Precio (USD)": precios_totales})
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X("Precio (USD)", bin=alt.Bin(maxbins=20)),
        alt.Y("count()", title="Frecuencia"),
        tooltip=["Precio (USD)", "count()"],
    ).properties(title="Distribución de precios de mercado (todas las fuentes)")
    st.altair_chart(chart, use_container_width=True)

    # IA Premium
    st.markdown("---")
    st.subheader("🤖 IA Premium (opcional)")

    if usar_ia_premium:
        comentario_ia = generar_comentario_ia(
            query, descripcion, precio_original, antiguedad, condicion, stats
        )
        if "VALOR_RECOMENDADO_FINAL:" in comentario_ia:
            try:
                partes = comentario_ia.split("VALOR_RECOMENDADO_FINAL:")[1]
                valor_str = partes.split("-")[0].strip().replace("$", "").replace(",", "")
                valor_str_clean = re.sub(r"[^\d.]", "", valor_str)
                valor_ia = float(valor_str_clean)
                justificacion = partes.split("-", 1)[1].strip()
                st.success(f"**IA Premium sugiere:** ${valor_ia:,.2f} USD — *{justificacion}*")
            except Exception as e:
                st.warning(f"La IA respondió, pero no se pudo interpretar el valor: {comentario_ia} (Error: {e})")
        else:
            st.warning(comentario_ia)
        st.caption("💳 Esta evaluación se considera una consulta premium simulada ($0.99).")
    else:
        st.info("Activa la IA Premium en la barra lateral para una recomendación final con justificación.")

    st.markdown("---")
    st.caption(
        "⚠️ Esta herramienta es una demo educativa. Las estimaciones son orientativas "
        "y no sustituyen una tasación profesional ni políticas internas."
    )
