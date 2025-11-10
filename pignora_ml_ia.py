import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI

# ==== CONFIGURACIÓN ====
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inicializar cliente de OpenAI solo si hay API Key
client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# ==== INTERFAZ ====
st.title("💰 Pignora - Estimador de Valor con Mercado + IA")

st.markdown("""
Esta herramienta estima el valor de empeño de un artículo combinando:
1️⃣ Comparación de precios reales en línea.  
2️⃣ Ajuste opcional con Inteligencia Artificial (requiere suscripción).  
""")

# ==== ENTRADAS ====
producto = st.text_input("🔍 ¿Qué artículo quieres tasar? (ej: 'iPhone 11 128GB')")
precio_original = st.number_input("💵 Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
antiguedad = st.slider("📆 Antigüedad (años)", 0, 15, 2)
condicion = st.slider("⚙️ Condición (1 = mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area("📝 Descripción del artículo", "iPhone 11, buen estado, con caja, ligeros rayones.")
fuente_datos = st.selectbox("🌐 Fuente de datos:", ["Mercado Libre", "Web scraping (Google)", "Automático (ambos)"])
usar_ia = st.checkbox("💡 Usar IA premium para comentario y ajuste (requiere suscripción)")

# ==== BOTÓN ====
if st.button("Calcular valor estimado"):
    if not producto:
        st.warning("Debes escribir un nombre de producto.")
        st.stop()

    precios = []

    # ==== 1️⃣ MERCADO LIBRE ====
    def buscar_mercado_libre(query):
        SITE_ID = "MLM"  # México por defecto (puedes cambiar por MLPA si existe para Panamá)
        search_url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search"
        params = {"q": query, "condition": "used", "limit": 30}
        try:
            resp = requests.get(search_url, params=params, timeout=10)
            data = resp.json()
            resultados = data.get("results", [])
            return [r["price"] for r in resultados if "price" in r]
        except Exception:
            return []

    # ==== 2️⃣ WEB SCRAPING (GOOGLE) ====
    def buscar_scraping(query):
        precios_scrap = []
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}+precio+usado"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            spans = soup.find_all("span")
            for s in spans:
                text = s.get_text()
                if "$" in text:
                    num = "".join([c for c in text if c.isdigit() or c == "."])
                    try:
                        val = float(num)
                        if 5 < val < 20000:
                            precios_scrap.append(val)
                    except:
                        pass
        except Exception:
            pass
        return precios_scrap

    # ==== LÓGICA DE FUENTE ====
    if fuente_datos == "Mercado Libre":
        precios = buscar_mercado_libre(producto)
    elif fuente_datos == "Web scraping (Google)":
        precios = buscar_scraping(producto)
    else:
        precios = buscar_mercado_libre(producto)
        if not precios:
            precios = buscar_scraping(producto)

    if not precios:
        st.error("❌ No se encontraron precios válidos en línea.")
        st.stop()

    # ==== CÁLCULOS ====
    precios_np = np.array(precios)
    promedio = np.mean(precios_np)
    mediana = np.median(precios_np)
    minimo = np.min(precios_np)
    maximo = np.max(precios_np)

    st.success(f"Se encontraron {len(precios)} precios en {fuente_datos}.")
    st.write(f"- Promedio: ${promedio:,.2f}")
    st.write(f"- Mediana: ${mediana:,.2f}")
    st.write(f"- Rango: ${minimo:,.2f} - ${maximo:,.2f}")

    # ==== 3️⃣ VALOR BASE ====
    st.subheader("💎 Cálculo base de empeño")

    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)
    factor_condicion = 0.3 + 0.07 * (condicion - 1)
    factor_riesgo = 0.6
    valor_base = mediana * factor_antiguedad * factor_condicion * factor_riesgo

    st.metric("Valor base estimado", f"${valor_base:,.2f}")

    # ==== 4️⃣ IA PREMIUM ====
    if usar_ia:
        if not OPENAI_API_KEY:
            st.error("No se detectó clave de API. No se puede usar IA premium.")
        else:
            st.subheader("🧠 Ajuste y comentario con IA")
            prompt = f"""
Eres un tasador experto en artículos de segunda mano en Latinoamérica.
Evalúa el siguiente artículo y su valor de empeño en Panamá.

Datos:
- Producto: {producto}
- Descripción: {descripcion}
- Precio original: {precio_original} USD
- Antigüedad: {antiguedad} años
- Condición: {condicion}/10
- Precio mediano de mercado: {mediana:.2f} USD
- Valor base calculado: {valor_base:.2f} USD

Responde en español con este formato exacto:
VALOR_RECOMENDADO: <monto en USD> - <comentario breve sobre el estado, mercado y razonabilidad del valor>.
"""
            try:
                with st.spinner("Consultando a la IA..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Eres un asistente experto en tasación de artículos de empeño."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.4,
                    )
                    texto_ia = response.choices[0].message.content.strip()
                    st.info(texto_ia)
            except Exception as e:
                st.error(f"Error consultando la IA: {e}")
    else:
        st.caption("💡 Puedes activar el ajuste con IA para obtener un comentario de valoración detallado.")
