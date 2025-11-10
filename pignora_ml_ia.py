import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI
import pandas as pd
import altair as alt # Para visualizaciones

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inicializar cliente de OpenAI solo si la API Key está presente
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador de Empeño", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
¡Bienvenido a Pignora! Esta herramienta te ayuda a estimar un valor de empeño combinando:

1.  **🏷️ Precios de Mercado:** Busca activamente precios de artículos similares en Mercado Libre (vía API y web scraping).
2.  **📉 Modelo de Depreciación:** Aplica ajustes por antigüedad y condición del artículo.
3.  **🤖 Ajuste Opcional con IA:** Ofrece una evaluación premium para una recomendación más precisa (simulado como $0.99 por evaluación).
""")

# ================== FUNCIONES DE UTILIDAD ==================

# Tasas de cambio simuladas (solo para la demo - en producción, usar una API real)
# Estas tasas son para convertir a USD
TASAS_CAMBIO_A_USD = {
    "MXN": 0.050,  # 1 MXN = 0.050 USD (ej. 20 MXN por 1 USD)
    "COP": 0.00025, # 1 COP = 0.00025 USD (ej. 4000 COP por 1 USD)
    "ARS": 0.0012,  # 1 ARS = 0.0012 USD (ej. 833 ARS por 1 USD)
    "USD": 1.0,
    "CLP": 0.0010, # Chile (ej. 1000 CLP por 1 USD)
    "PEN": 0.27,   # Perú (ej. 3.7 PEN por 1 USD)
}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    """Convierte un precio de su moneda original a USD usando tasas simuladas."""
    moneda_origen = moneda_origen.upper()
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen)
    if tasa:
        return precio * tasa
    st.warning(f"⚠️ Moneda '{moneda_origen}' no reconocida en la demo para conversión. Asumiendo que el precio ya está en USD.")
    return precio

def construir_query(categoria: str, modelo: str) -> str:
    """Construye la cadena de búsqueda para Mercado Libre."""
    base = categoria if categoria != "Otro" else ""
    texto = (base + " " + modelo).strip()
    return texto if texto else modelo

def buscar_mercado_libre_api(query: str):
    """
    Busca precios en Mercado Libre usando la API oficial.
    Intenta en varios países hasta encontrar resultados.
    Devuelve precios ya convertidos a USD.
    """
    sites = {
        "MLM": "México",  # MXN
        "MCO": "Colombia",  # COP
        "MLA": "Argentina", # ARS
        "MLC": "Chile",   # CLP
        "MPE": "Perú"     # PEN
    }
    todos_precios_usd = []
    todos_resultados_crudos = []
    sitio_usado = None

    for site_id, pais_nombre in sites.items():
        url = f"https://api.mercadolibre.com/sites/{site_id}/search"
        params = {"q": query, "condition": "used", "limit": 20} # Menos items para demo rápida
        try:
            resp = requests.get(url, params=params, timeout=5) # Menos timeout para demo
            resp.raise_for_status() # Lanza un error para códigos de estado HTTP erróneos
            data = resp.json()
            resultados = data.get("results", [])

            precios_site = []
            for r in resultados:
                if "price" in r and "currency_id" in r:
                    precio_usd = convertir_a_usd(r["price"], r["currency_id"])
                    precios_site.append(precio_usd)
            
            if precios_site:
                todos_precios_usd.extend(precios_site)
                # Almacenar un subconjunto para no sobrecargar la UI
                todos_resultados_crudos.extend([
                    {"title": item.get("title", "")[:60] + "...",
                     "price_original": item.get("price", 0.0),
                     "currency_id": item.get("currency_id", ""),
                     "price_usd": convertir_a_usd(item.get("price", 0.0), item.get("currency_id", "")),
                     "permalink": item.get("permalink", ""),
                     "site": site_id}
                    for item in resultados[:5] # Limitar a 5 resultados por site para la tabla
                ])
                sitio_usado = site_id # Solo para indicar de dónde se obtuvieron los primeros datos
                # Para la demo, podemos parar aquí si encontramos algo
                break 

        except requests.exceptions.RequestException as e:
            # st.info(f"No se obtuvieron resultados de la API para {pais_nombre}: {e}")
            pass # Silenciar errores de conexión para otros sitios en la demo
        except Exception as e:
            st.error(f"Error inesperado al buscar en {pais_nombre} (API): {e}")
            
    return todos_precios_usd, todos_resultados_crudos, sitio_usado


def buscar_mercado_libre_scraping(query: str):
    """
    Realiza scraping de la web de Mercado Libre México para precios.
    Devuelve precios ya convertidos a USD.
    """
    slug = query.replace(" ", "-")
    url = f"https://listado.mercadolibre.com.mx/{slug}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.mercadolibre.com.mx/",
    }

    precios_usd = []
    try:
        resp = requests.get(url, headers=headers, timeout=5) # Menos timeout para demo
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Intentar diferentes selectores para precios, ya que pueden variar
        price_spans = soup.select("span.andes-money-amount__fraction") # Selector principal
        if not price_spans: # Si no encuentra el principal, probar otro común
            price_spans = soup.select(".ui-search-price__part.ui-search-price__part--medium .andes-money-amount__fraction")

        for span in price_spans:
            txt = span.get_text(strip=True).replace(".", "").replace(",", "")
            try:
                val_mxn = float(txt)
                # Filtrar valores extremos que podrían ser errores de scraping
                if 50 < val_mxn < 500000: # Rango más amplio para MXN
                    precios_usd.append(convertir_a_usd(val_mxn, "MXN"))
            except ValueError:
                continue
    except requests.exceptions.RequestException as e:
        # st.info(f"No se pudo realizar scraping en ML México: {e}")
        pass # Silenciar errores de conexión/scraping para la demo
    except Exception as e:
        st.error(f"Error inesperado durante el scraping: {e}")

    return precios_usd


def calcular_valor_empeno(precios_usd: list, antiguedad: int, condicion: int):
    """
    Calcula el valor de empeño base ajustado por antigüedad y condición.
    Todos los precios deben estar ya en USD.
    """
    if not precios_usd:
        return None

    precios_np = np.array(precios_usd)
    mediana = float(np.median(precios_np))
    promedio = float(np.mean(precios_np))
    minimo = float(np.min(precios_np))
    maximo = float(np.max(precios_np))

    # Modelo de depreciación:
    # Factor antigüedad: Cae 8-10% por año, con un mínimo del 20-30% de su valor original.
    factor_antiguedad = max(0.30, 1 - 0.10 * antiguedad) # Mínimo 30% del valor de mercado

    # Factor condición: De 0.4 (muy mala) a 1.0 (excelente).
    factor_condicion = 0.4 + 0.06 * (condicion - 1) # (1-10) -> (0 a 9) * 0.06 = 0 a 0.54. Sumado a 0.4 da 0.4 a 0.94. Ajustar un poco
    factor_condicion = round(min(1.0, factor_condicion), 2) # Asegurarse que no exceda 1.0 y redondear

    # Factor de riesgo y ganancia de la casa de empeño (prestamos un % del valor de mercado ajustado)
    factor_riesgo_ganancia = 0.55 # Prestamos el 55% del valor de mercado ajustado por depreciación

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


def generar_comentario_ia(query: str, descripcion: str, precio_original: float, antiguedad: int, condicion: int, stats: dict):
    """
    Genera un comentario de IA con una recomendación de valor de empeño.
    Requiere una API key de OpenAI.
    """
    if not client:
        return "⚠️ IA no disponible: No se encontró la API key de OpenAI. Por favor, configúrala en el archivo '.env'."

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica, conocido por tus recomendaciones realistas y equilibradas.

Artículo a evaluar:
- Búsqueda principal: "{query}"
- Descripción del usuario: "{descripcion}"
- Precio original (nuevo): {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición (1-10): {condicion}/10

Datos de mercado (ya en USD):
- Mediana: {stats['mediana']:.2f} USD
- Promedio: {stats['promedio']:.2f} USD
- Rango de mercado: {stats['minimo']:.2f} - {stats['maximo']:.2f} USD

Factores aplicados por el sistema:
- Por antigüedad ({antiguedad} años): {stats['factor_antiguedad']:.2f}
- Por condición ({condicion}/10): {stats['factor_condicion']:.2f}
- Factor de riesgo y ganancia de empeño: {stats['factor_riesgo_ganancia']:.2f}

Valor base estimado por el sistema (antes de tu IA): {stats['valor_base']:.2f} USD.

Tu tarea:
Basándote en toda la información, propón un valor de empeño final que sea realista y atractivo para el cliente,
y justifica tu recomendación en **máximo 20 palabras**. Ajusta el valor base del sistema si lo consideras apropiado.
Recuerda que los clientes buscan el mejor trato posible, pero la casa de empeño debe ser rentable.

Formato EXACTO de respuesta (importante para el procesamiento):
VALOR_RECOMENDADO_FINAL: <número en USD> - <tu justificación concisa>.
"""

    try:
        with st.spinner("La IA está evaluando el artículo..."):
            resp = client.chat.completions.create(
                model="gpt-4o-mini", # Modelo más económico y rápido para demos
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un tasador de empeño que equilibra la oferta justa con la rentabilidad.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4, # Un poco más creativo pero aún enfocado
                max_tokens=100 # Para respuestas concisas
            )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}. Asegúrate de que tu API Key sea válida y tengas créditos."

# ================== INTERFAZ DE USUARIO (Streamlit) ==================

with st.sidebar:
    st.header("⚙️ Configuración del Artículo")
    categoria = st.selectbox(
        "Tipo de artículo",
        [
            "Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
            "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro",
        ],
    )
    modelo = st.text_input("Modelo / Referencia (ej: 'Dell Vostro 3500', 'iPhone 11 128GB')", "iPhone 12 128GB")
    descripcion = st.text_area(
        "Descripción del artículo",
        "Buen estado general, uso moderado, incluye cargador y caja, pequeños rayones en pantalla.",
    )

    st.subheader("📊 Detalles de Valoración")
    precio_original = st.number_input(
        "Precio original (nuevo, USD)", min_value=10.0, value=799.0, step=10.0, format="%.2f"
    )
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 2)
    condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 7)

    st.subheader("🌐 Fuentes de Datos")
    col_api, col_scrap = st.columns(2)
    with col_api:
        usar_api_ml = st.checkbox("API Mercado Libre", value=True, help="Busca precios a través de la API oficial.")
    with col_scrap:
        usar_scraping_ml = st.checkbox("Scraping Web ML", value=True, help="Complementa con búsqueda directa en la web de Mercado Libre.")

    st.subheader("💡 Funcionalidad Premium")
    usar_ia_premium = st.checkbox(
        "Activar IA premium (simula costo de $0.99)", value=False,
        help="Obtén una recomendación final y justificación de un tasador IA. (En un entorno real, esto tendría un costo)."
    )
    if usar_ia_premium:
        st.info("Simulando cobro de $0.99 por esta evaluación de IA.")


# Botón principal para calcular la estimación
st.markdown("---")
if st.button("🚀 Calcular Estimación de Empeño", type="primary", use_container_width=True):
    if not modelo and categoria == "Otro":
        st.error("❌ Por favor, especifica al menos un modelo o selecciona una categoría conocida para la búsqueda.")
        st.stop()

    query = construir_query(categoria, modelo)
    st.subheader(f"🔍 Evaluando: '{query}'")

    # Contenedor para mostrar resultados de búsqueda
    col_ml_api, col_ml_scrap = st.columns(2)
    precios_totales_usd = []
    resultados_ml_df = pd.DataFrame()

    with col_ml_api:
        st.markdown("##### 1️⃣ Búsqueda en Mercado Libre (API)")
        with st.spinner("Buscando en Mercado Libre vía API..."):
            precios_api_usd, resultados_crudos_api, site_usado = buscar_mercado_libre_api(query)
            if precios_api_usd:
                st.success(f"✔️ Encontrados {len(precios_api_usd)} precios en el sitio {site_usado} (vía API).")
                if resultados_crudos_api:
                    df_api = pd.DataFrame(resultados_crudos_api)
                    df_api = df_api[['title', 'price_original', 'currency_id', 'price_usd', 'site']]
                    st.dataframe(df_api, use_container_width=True, hide_index=True,
                                 column_config={"permalink": st.column_config.LinkColumn("Link")})
                    precios_totales_usd.extend(precios_api_usd)
                    resultados_ml_df = pd.concat([resultados_ml_df, df_api])
            else:
                st.info("No se encontraron resultados relevantes vía API.")

    with col_ml_scrap:
        st.markdown("##### 2️⃣ Búsqueda en Mercado Libre (Web Scraping)")
        if usar_scraping_ml:
            with st.spinner("Buscando en Mercado Libre vía Web Scraping (México)..."):
                precios_scrap_usd = buscar_mercado_libre_scraping(query)
                if precios_scrap_usd:
                    st.success(f"✔️ Encontrados {len(precios_scrap_usd)} precios en ML México (vía Web Scraping).")
                    df_scrap = pd.DataFrame([{"Fuente": "ML Web MX", "Precio USD": p} for p in precios_scrap_usd])
                    st.dataframe(df_scrap, use_container_width=True, hide_index=True)
                    precios_totales_usd.extend(precios_scrap_usd)
                else:
                    st.info("No se encontraron precios relevantes vía Web Scraping.")
        else:
            st.info("Web Scraping desactivado.")
    
    st.markdown("---")

    if not precios_totales_usd:
        st.error("❌ Lo sentimos, no se pudo obtener ningún precio de referencia. Intenta ajustar el modelo o la descripción.")
        st.stop()

    # ================== CÁLCULO BASE DE VALOR ==================
    st.subheader("3️⃣ Análisis de Mercado y Cálculo Base")
    
    # Asegurarse de que no haya precios cero o nulos que puedan distorsionar
    precios_filtrados = [p for p in precios_totales_usd if p is not None and p > 0]
    if not precios_filtrados:
        st.error("❌ No hay precios válidos para calcular la estimación. Revisa las fuentes de datos.")
        st.stop()

    stats = calcular_valor_empeno(precios_filtrados, antiguedad, condicion)

    if stats is None:
        st.error("❌ No se pudo calcular el valor de empeño. Esto puede ocurrir si no hay suficientes datos válidos.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Mediana de Mercado (USD)", f"${stats['mediana']:,.2f}")
    col2.metric("📊 Promedio de Mercado (USD)", f"${stats['promedio']:,.2f}")
    col3.metric("⬇️ Mínimo Encontrado (USD)", f"${stats['minimo']:,.2f}")
    col4.metric("⬆️ Máximo Encontrado (USD)", f"${stats['maximo']:,.2f}")

    st.markdown("#### Factores de Ajuste Aplicados:")
    col_fact1, col_fact2, col_fact3 = st.columns(3)
    col_fact1.info(f"**Factor por Antigüedad ({antiguedad} años):** {stats['factor_antiguedad']:.2f}")
    col_fact2.info(f"**Factor por Condición ({condicion}/10):** {stats['factor_condicion']:.2f}")
    col_fact3.info(f"**Factor de Empeño (Riesgo/Ganancia):** {stats['factor_riesgo_ganancia']:.2f}")

    st.markdown("---")
    st.subheader(f"✅ Valor Base Sugerido de Empeño: **${stats['valor_base']:,.2f} USD**")
    st.markdown("Este valor es una estimación inicial aplicando los factores de depreciación y el margen de empeño.")

    # Visualización de la distribución de precios
    st.markdown("#### Distribución de Precios de Mercado Encontrados (USD)")
    df_precios = pd.DataFrame({'Precio (USD)': precios_filtrados})
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X('Precio (USD)', bin=True),
        alt.Y('count()', title='Frecuencia'),
        tooltip=['Precio (USD)', 'count()']
    ).properties(
        title='Histograma de Precios Convertidos a USD'
    )
    st.altair_chart(chart, use_container_width=True)

    # ================== IA PREMIUM ==================
    st.subheader("4️⃣ Ajuste con Inteligencia Artificial Premium (Opcional)")

    if usar_ia_premium:
        comentario_ia = generar_comentario_ia(
            query, descripcion, precio_original, antiguedad, condicion, stats
        )
        st.markdown("---")
        if "VALOR_RECOMENDADO_FINAL:" in comentario_ia:
            try:
                parts = comentario_ia.split("VALOR_RECOMENDADO_FINAL:")
                valor_str = parts[1].split('-')[0].strip().replace("$", "").replace(",", "")
                valor_ia = float(valor_str)
                justificacion = parts[1].split('-')[1].strip()
                st.success(f"**Recomendación IA Premium:** **${valor_ia:,.2f} USD** - *{justificacion}*")
            except Exception:
                st.warning(f"La IA respondió, pero no pude parsear el formato: {comentario_ia}")
        else:
            st.warning(comentario_ia)
        st.caption("💳 Esta evaluación se considera una consulta premium (simulando un costo de $0.99).")
    else:
        st.info("💡 Activa la **IA Premium** en la barra lateral para obtener una recomendación final y justificación más personalizada.")

    st.markdown("---")
    st.caption("⚠️ **Descargo de Responsabilidad:** Esta herramienta es una *demostración* y proporciona una estimación orientativa. No reemplaza una tasación profesional, políticas internas, ni criterios regulatorios de una casa de empeño real. Las tasas de cambio y los precios de mercado pueden variar.")