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

if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None

st.title("💰 Pignora - Estimador de Valor con IA y Web Scraping")

st.markdown("""
Esta herramienta permite estimar el valor de empeño de un artículo mediante:
1. Comparaciones de precios en línea (web scraping).  
2. Ajuste opcional mediante IA.  
""")

# ==== ENTRADAS DEL USUARIO ====
producto = st.text_input("🔍 ¿Qué artículo quieres tasar? (ej: 'iPhone 11 128GB')")
precio_original = st.number_input("💵 Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
antiguedad = st.slider("📆 Antigüedad (años)", 0, 15, 2)
condicion = st.slider("⚙️ Condición (1 = mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area("📝 Descripción del artículo (opcional)", "iPhone 11 con caja, batería 85%, ligeros rayones.")
usar_ia = st.checkbox("💡 Usar IA para comentario y ajuste (requiere suscripción)")

if st.button("Calcular valor estimado"):
    if not producto:
        st.warning("Debes escribir un nombre de producto.")
        st.stop()

    st.subheader("1️⃣ Búsqueda de precios en línea")

    # ==== SCRAPING ====
    query = producto.replace(" ", "+")
    url = f"https://www.google.com/search?q={query}+usado+precio"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    precios = []

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
                    if 5 < val < 10000:
                        precios.append(val)
                except:
                    pass

        if not precios:
            st.warning("No se encontraron precios válidos en la web.")
            st.stop()

        promedio = np.mean(precios)
        mediana = np.median(precios)
        minimo = np.min(precios)
        maximo = np.max(precios)

        st.write(f"**Precios encontrados:** {len(precios)}")
        st.write(f"- Promedio: ${promedio:,.2f}")
        st.write(f"- Mediana: ${mediana:,.2f}")
        st.write(f"- Rango: ${minimo:,.2f} - ${maximo:,.2f}")

    except Exception as e:
        st.error(f"Error en scraping: {e}")
        st.stop()

    # ==== CÁLCULO BASE ====
    st.subheader("2️⃣ Cálculo base de empeño")

    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)
    factor_condicion = 0.3 + 0.07 * (condicion - 1)
    factor_riesgo = 0.6

    valor_base = mediana * factor_antiguedad * factor_condicion * factor_riesgo
    st.metric("Valor base estimado", f"${valor_base:,.2f}")

    # ==== IA (OPCIONAL) ====
    st.subheader("3️⃣ Ajuste con IA (opcional)")

    if usar_ia and client:
        prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Producto: {producto}
Descripción: {descripcion}
Precio original: {precio_original:.2f} USD
Valor base calculado: {valor_base:.2f} USD
Antigüedad: {antiguedad} años
Condición: {condicion}/10

Con base en esta información, propone un valor de empeño final y una breve justificación (máximo 25 palabras).
"""

        try:
            with st.spinner("Consultando IA..."):
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Eres un tasador preciso y realista."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                )
                comentario = response.choices[0].message.content.strip()
                st.success(comentario)
        except Exception as e:
            st.warning(f"Error consultando la IA: {e}")
    else:
        st.info("La IA está desactivada. Solo se muestra el valor estimado basado en precios de mercado.")

    st.caption("💡 Este cálculo es orientativo y combina datos de mercado con factores técnicos de depreciación.")
