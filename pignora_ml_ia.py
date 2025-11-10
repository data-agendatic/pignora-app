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

client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

# ==== INTERFAZ ====
st.title("💰 Pignora - Estimador de Valor con Mercado + IA")

st.markdown("""
Esta herramienta estima el valor de empeño de un artículo combinando:
1️⃣ Comparación de precios reales en línea (Mercado Libre o Google Shopping).  
2️⃣ Ajuste opcional con Inteligencia Artificial (requiere suscripción).  
""")

# ==== ENTRADAS ====
producto = st.text_input("🔍 ¿Qué artículo quieres tasar? (ej: 'Laptop Dell Vostro')")
precio_original = st.number_input("💵 Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
antiguedad = st.slider("📆 Antigüedad (años)", 0, 15, 2)
condicion = st.slider("⚙️ Condición (1 = mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area("📝 Descripción del artículo", "Laptop Dell Vostro usada, buen estado, 8GB RAM, SSD 256GB.")
fuente_datos = st.selectbox("🌐 Fuente de precios:", ["Automático (ambos)", "Mercado Libre", "Google Shopping"])
usar_ia = st.checkbox("💡 Usar IA premium para comentario y ajuste (requiere suscripción)")

# ==== FUNCIONES ====

def buscar_mercado_libre(query):
    """Busca precios usados en Mercado Libre."""
    SITE_ID = "MLM"  # México (puedes cambiar a MLPA si existe Panamá)
    url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search"
    params = {"q": query, "condition": "used", "limit": 30}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        resultados = data.get("results", [])
        precios = [r["price"] for r in resultados if "price" in r]
        return precios
    except Exception:
        return []


def buscar_google_shopping(query):
    """Scraping desde Google Shopping."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/",
    }

    url = f"https://www.google.com/search?tbm=shop&q={query.replace(' ', '+')}"
    precios = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for span in soup.select("div.a8Pemb"):
            text = span.get_text()
            if "$" in text:
                try:
                    val = float(text.replace("$", "").replace(",", "").strip())
                    if 10 < val < 20000:
                        precios.append(val)
                except:
                    pass
    except Exception:
        pass
    return precios


def calcular_valor_empeno(precios, antiguedad, condicion):
    """Cálculo del valor base de empeño."""
    precios_np = np.array(precios)
    mediana = np.median(precios_np)
    factor_ant = max(0.2, 1 - 0.08 * antiguedad)
    factor_cond = 0.3 + 0.07 * (condicion - 1)
    factor_riesgo = 0.6
    valor = mediana * factor_ant * factor_cond * factor_riesgo
    return valor, mediana


def generar_comentario_ia(producto, descripcion, precio_original, antiguedad, condicion, mediana, valor_base):
    """Comentario y ajuste con IA."""
    prompt = f"""
Eres un tasador experto en artículos usados y casas de empeño en Latinoamérica.

Datos del artículo:
- Producto: {producto}
- Descripción: {descripcion}
- Precio original: {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición: {condicion}/10
- Precio mediano de mercado: {mediana:.2f} USD
- Valor base calculado: {valor_base:.2f} USD

Tarea:
Propón un valor de empeño final (realista para Panamá o Latam) y una breve justificación (máx. 25 palabras).

Responde en español con este formato exacto:
VALOR_RECOMENDADO: <número en USD> - <comentario breve>.
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un experto tasador realista y preciso."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Error consultando la IA: {e}"


# ==== BOTÓN ====
if st.button("Calcular valor estimado"):
    if not producto:
        st.warning("Por favor, ingresa un nombre de producto.")
        st.stop()

    st.subheader("1️⃣ Búsqueda de precios en línea")

    precios = []
    if fuente_datos == "Mercado Libre":
        precios = buscar_mercado_libre(producto)
    elif fuente_datos == "Google Shopping":
        precios = buscar_google_shopping(producto)
    else:  # Automático
        precios = buscar_mercado_libre(producto)
        if not precios:
            precios = buscar_google_shopping(producto)

    if not precios:
        st.error("No se encontraron precios válidos en línea.")
        st.stop()

    promedio = np.mean(precios)
    mediana = np.median(precios)
    minimo = np.min(precios)
    maximo = np.max(precios)

    st.success(f"Se encontraron {len(precios)} precios.")
    st.write(f"- Promedio: ${promedio:,.2f}")
    st.write(f"- Mediana: ${mediana:,.2f}")
    st.write(f"- Rango: ${minimo:,.2f} - ${maximo:,.2f}")

    # ==== CÁLCULO BASE ====
    st.subheader("2️⃣ Cálculo base de empeño")
    valor_base, mediana_final = calcular_valor_empeno(precios, antiguedad, condicion)
    st.metric("Valor base estimado", f"${valor_base:,.2f}")

    # ==== IA (opcional) ====
    st.subheader("3️⃣ Ajuste y comentario con IA")
    if usar_ia:
        if not OPENAI_API_KEY:
            st.warning("⚠️ No hay clave API configurada. La función premium de IA no está disponible.")
        else:
            with st.spinner("Consultando IA..."):
                comentario = generar_comentario_ia(
                    producto, descripcion, precio_original, antiguedad, condicion, mediana_final, valor_base
                )
                st.info(comentario)
    else:
        st.caption("💡 Activa la opción de IA para recibir un comentario de valoración ajustado y una justificación breve.")

    st.caption("🔸 Esta estimación es orientativa, basada en datos públicos de mercado y factores técnicos de depreciación.")
