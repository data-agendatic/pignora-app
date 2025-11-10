import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI
import pandas as pd
import altair as alt # Para visualizaciones
import re # Para expresiones regulares en scraping

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
    "UYU": 0.025,  # Uruguay (ej. 40 UYU por 1 USD)
    "BRL": 0.20,   # Brasil (ej. 5 BRL por 1 USD)
}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    """Convierte un precio de su moneda original a USD usando tasas simuladas."""
    moneda_origen = moneda_origen.upper()
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen)
    if tasa:
        return precio * tasa
    # st.warning(f"⚠️ Moneda '{moneda_origen}' no reconocida en la demo para conversión. Asumiendo que el precio ya está en USD.")
    return precio # Retorna el precio original si la moneda no está en la tabla

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
        "MPE": "Perú",     # PEN
        "MLU": "Uruguay",  # UYU
        "MLB": "Brasil"    # BRL
    }
    todos_precios_usd = []
    todos_resultados_crudos = []
    sitio_usado = None

    for site_id, pais_nombre in sites.items():
        url = f"https://api.mercadolibre.com/sites/{site_id}/search"
        params = {"q": query, "condition": "used", "limit": 20} # Menos items para demo rápida
        try:
            resp = requests.get(url, params=params, timeout=7) # Aumentar un poco el timeout
            resp.raise_for_status() # Lanza un error para códigos de estado HTTP erróneos
            data = resp.json()
            resultados = data.get("results", [])

            precios_site = []
            for r in resultados:
                if "price" in r and "currency_id" in r:
                    precio_usd = convertir_a_usd(r["price"], r["currency_id"])
                    if precio_usd > 0: # Solo considerar precios válidos
                        precios_site.append(precio_usd)
            
            if precios_site:
                todos_precios_usd.extend(precios_site)
                # Almacenar un subconjunto para no sobrecargar la UI
                for item in resultados[:5]: # Limitar a 5 resultados por site para la tabla
                     if "price" in item and "currency_id" in item:
                        todos_resultados_crudos.append({
                            "Título": item.get("title", "")[:60] + "...",
                            "Precio Original": f"{item.get('price', 0.0):,.2f} {item.get('currency_id', '')}",
                            "Precio USD": convertir_a_usd(item.get("price", 0.0), item.get("currency_id", "")),
                            "Link": item.get("permalink", ""),
                            "Sitio": site_id
                        })
                sitio_usado = site_id # Solo para indicar de dónde se obtuvieron los primeros datos
                # Para la demo, podemos parar aquí si encontramos algo
                break 

        except requests.exceptions.Timeout:
            # st.info(f"Tiempo de espera agotado para la API de ML en {pais_nombre}.")
            pass
        except requests.exceptions.RequestException as e:
            # st.info(f"Error en la API de ML para {pais_nombre}: {e}")
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
    # Intentar con un dominio más genérico o específico si sabes dónde quieres buscar primero
    url = f"https://listado.mercadolibre.com.mx/{slug}" 
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.mercadolibre.com.mx/",
        "DNT": "1", # Do Not Track
        "Connection": "keep-alive"
    }

    precios_usd = []
    try:
        resp = requests.get(url, headers=headers, timeout=10) # Aumentar timeout para scraping
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # --- SELECTORES MÁS ROBUSTOS / ALTERNATIVOS ---
        # 1. Selector principal (el que usabas)
        price_tags = soup.select("span.andes-money-amount__fraction") 
        
        # 2. Selector alternativo para listados más recientes o diferentes layouts
        if not price_tags:
            price_tags = soup.select("div.ui-search-price__second-line span.andes-money-amount__fraction")
        
        # 3. Otro selector posible que a veces aparece
        if not price_tags:
            price_tags = soup.select("span.andes-money-amount__parts:first-child .andes-money-amount__fraction")

        # 4. Fallback: Buscar cualquier texto que parezca un precio dentro de elementos de listado
        if not price_tags:
            # Esto es más un comodín y puede ser menos preciso
            items = soup.select(".ui-search-layout__item")
            for item in items:
                price_text = item.find(text=re.compile(r'\$\s*\d[\d\.,]*'))
                if price_text:
                    clean_price = price_text.replace('$', '').replace('.', '').replace(',', '').strip()
                    try:
                        val_mxn = float(clean_price)
                        if 50 < val_mxn < 500000:
                            precios_usd.append(convertir_a_usd(val_mxn, "MXN"))
                    except ValueError:
                        continue
            if precios_usd: # Si encontró algo con el fallback, salir
                return precios_usd

        if not price_tags:
            st.info("Scraping: No se encontraron elementos de precio con ninguno de los selectores definidos.")
            return [] # Retornar vacío si no se encontró nada

        for span in price_tags:
            txt = span.get_text(strip=True).replace(".", "").replace(",", "")
            try:
                val_mxn = float(txt)
                if 50 < val_mxn < 5000000: # Rango más amplio para MXN
                    precios_usd.append(convertir_a_usd(val_mxn, "MXN"))
            except ValueError:
                continue
    except requests.exceptions.Timeout:
        st.warning("⚠️ Scraping: Tiempo de espera agotado al intentar acceder a Mercado Libre.")
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Scraping: Error de red o HTTP al intentar acceder a Mercado Libre: {e}")
    except Exception as e:
        st.error(f"⚠️ Scraping: Error inesperado durante el proceso: {e}")

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
    # Ajuste: (condicion-1) / 9 escala de 0 a 1. Luego se aplica un rango.
    factor_condicion = 0.4 + (0.6 * (condicion - 1) / 9) # Rango de 0.4 (condición 1) a 1.0 (condición 10)
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
    modelo = st.text_input("Modelo / Referencia (ej: 'Dell Vostro 3500', 'iPhone 11 128GB')", "PlayStation 4")
    descripcion = st.text_area(
        "Descripción del artículo",
        "Buen estado general, uso moderado, incluye cargador y caja, pequeños rayones en pantalla.",
    )

    st.subheader("📊 Detalles de Valoración")
    precio_original = st.number_input(
        "Precio original (nuevo, USD)", min_value=10.0, value=500.0, step=10.0, format="%.2f"
    )
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
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
                st.success(f"✔️ Encontrados {len(precios_api_usd)} precios en el sitio {site_usado if site_usado else 'varios'} (vía API).")
                if resultados_crudos_api:
                    df_api = pd.DataFrame(resultados_crudos_api)
                    st.dataframe(df_api, use_container_width=True, hide_index=True,
                                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="Ver →")})
                    precios_totales_usd.extend(precios_api_usd)
                    # resultados_ml_df = pd.concat([resultados_ml_df, df_api]) # No concatenar aquí para no duplicar en la tabla inferior
            else:
                st.info("No se encontraron resultados relevantes vía API.")

    with col_ml_scrap:
        st.markdown("##### 2️⃣ Búsqueda en Mercado Libre (Web Scraping)")
        if usar_scraping_ml:
            with st.spinner("Buscando en Mercado Libre vía Web Scraping (México)..."):
                precios_scrap_usd = buscar_mercado_libre_scraping(query)
                if precios_scrap_usd:
                    st.success(f"✔️ Encontrados {len(precios_scrap_usd)} precios en ML México (vía Web Scraping).")
                    df_scrap = pd.DataFrame([{"Fuente": "ML Web MX", "Precio USD": f"{p:,.2f}"} for p in precios_scrap_usd[:10]]) # Mostrar top 10
                    st.dataframe(df_scrap, use_container_width=True, hide_index=True)
                    precios_totales_usd.extend(precios_scrap_usd)
                else:
                    st.info("No se encontraron precios relevantes vía Web Scraping. Esto puede ocurrir si el sitio ha cambiado su estructura.")
        else:
            st.info("Web Scraping desactivado.")
    
    st.markdown("---")

    if not precios_totales_usd:
        st.error("❌ Lo sentimos, no se pudo obtener ningún precio de referencia. Intenta ajustar el modelo o la descripción y/o verifica que las fuentes estén activas.")
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
    
    # Asegurarse de que el rango de precios para el histograma sea razonable
    # Evitar que un solo valor muy atípico distorsione el histograma
    min_chart_price = df_precios['Precio (USD)'].quantile(0.05) if not df_precios.empty else 0
    max_chart_price = df_precios['Precio (USD)'].quantile(0.95) if not df_precios.empty else 1000
    
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X('Precio (USD)', bin=alt.Bin(maxbins=20), scale=alt.Scale(domain=[min_chart_price, max_chart_price])),
        alt.Y('count()', title='Frecuencia'),
        tooltip=['Precio (USD)', 'count()']
    ).properties(
        title='Histograma de Precios Convertidos a USD (Rango principal)'
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
                # Eliminar cualquier texto que no sea numérico al final de valor_str
                valor_str_clean = re.sub(r'[^\d.]+', '', valor_str)
                valor_ia = float(valor_str_clean)
                justificacion = parts[1].split('-', 1)[1].strip() # Usar split con maxsplit=1 para el resto
                st.success(f"**Recomendación IA Premium:** **${valor_ia:,.2f} USD** - *{justificacion}*")
            except Exception as e:
                st.warning(f"La IA respondió, pero no pude parsear el formato: {comentario_ia}. Error: {e}")
        else:
            st.warning(comentario_ia)
        st.caption("💳 Esta evaluación se considera una consulta premium (simulando un costo de $0.99).")
    else:
        st.info("💡 Activa la **IA Premium** en la barra lateral para obtener una recomendación final y justificación más personalizada.")

    st.markdown("---")
    st.caption("⚠️ **Descargo de Responsabilidad:** Esta herramienta es una *demostración* y proporciona una estimación orientativa. No reemplaza una tasación profesional, políticas internas, ni criterios regulatorios de una casa de empeño real. Las tasas de cambio y los precios de mercado pueden variar.")