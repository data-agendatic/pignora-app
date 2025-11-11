import re, requests, numpy as np, pandas as pd, feedparser, altair as alt, streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI
from requests.structures import CaseInsensitiveDict

# ================== CONFIGURACIÓN INICIAL ==================
# Coloca aquí tu clave de OpenAI si quieres usar IA:
OPENAI_API_KEY = None  # ejemplo: "sk-xxxx..."
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Clave de Metals.dev (la que mostraste en el dashboard)
METALSDEV_API_KEY = "HD5SVRDTPC4P0UWJ0ATH699WJ0ATH"

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
    if not modelo and not categoria:
        return ""
    if not modelo:
        return categoria
    if not categoria or categoria.lower() in modelo.lower():
        return modelo
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
            if 20 < val < 10000:
                precios.append(val)
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
    st.markdown(f"🔹 **Google Shopping:** [{url}]({url})")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
        matches = re.findall(r"\$\s?\d{2,5}(?:\.\d{2})?", text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 10 < val < 10000:
                precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception:
        return [], []

def buscar_encuentra24(query: str):
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []
    st.markdown(f"🔹 **Encuentra24:** [{url}]({url})")
    try:
        feed = feedparser.parse(url)
        palabras = [w.lower() for w in query.split() if len(w) > 2]
        for entry in feed.entries[:60]:
            texto = f"{entry.get('title','')} {entry.get('summary','')}".lower()
            if not any(p in texto for p in palabras):
                continue
            matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", texto)
            for m in matches:
                val = float(m)
                if 20 < val < 10000:
                    precios.append(val)
                    resultados.append({
                        "Fuente": "Encuentra24",
                        "Título": entry.title[:60] + "...",
                        "Precio USD": val,
                        "Link": entry.link
                    })
        return precios, resultados
    except Exception:
        return [], []

# ================== IA SEMÁNTICA (PRECIOS EXTRA) ==================
def buscar_ia_semantica(query: str):
    if not client:
        st.warning("⚠️ IA semántica no disponible (sin OPENAI_API_KEY).")
        return [], []
    prompt = f"Da 3 precios plausibles en USD para un artículo usado llamado: '{query}'. Solo lista números, por ejemplo: 320, 290, 410"
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=50,
        )
        texto = resp.choices[0].message.content
        precios = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", texto) if 10 < float(x) < 10000]
        resultados = [{"Fuente": "IA semántica", "Título": query, "Precio USD": p, "Link": "IA"} for p in precios]
        return precios, resultados
    except Exception as e:
        st.warning(f"IA semántica falló: {e}")
        return [], []

# ================== ORO (API METALS.DEV) ==================
def obtener_precio_oro_por_gramo(api_key: str) -> float:
    """Consulta el precio actual del oro en USD/gramo usando Metals.dev."""
    try:
        url = f"https://api.metals.dev/v1/latest?api_key={api_key}&currency=USD&unit=toz"
        headers = CaseInsensitiveDict()
        headers["Accept"] = "application/json"
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        # Estructura típica: {"metals": {"XAU": {"price": 2350.12, ...}}, ...}
        if "metals" in data and "XAU" in data["metals"]:
            precio_onza = data["metals"]["XAU"]["price"]
            precio_gramo = precio_onza / 31.1035
            return round(precio_gramo, 2)
        else:
            st.warning("⚠️ API Metals.dev sin datos válidos, usando 75 USD/g.")
            return 75.0
    except Exception as e:
        st.warning(f"⚠️ Error consultando API Metals.dev: {e} — usando 75 USD/g.")
        return 75.0

def estimar_oro(peso_gramos: float, pureza: int, api_key: str):
    precio_oro_puro = obtener_precio_oro_por_gramo(api_key)
    factor_pureza = pureza / 24
    valor_bruto = peso_gramos * precio_oro_puro * factor_pureza
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2), precio_oro_puro

# ================== ACTIVOS DIGITALES ==================
def estimar_activo_digital(url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    site = url.replace("https://", "").replace("http://", "").split("/")[0]
    check = f"https://www.siteprice.org/website-worth/{site}"
    st.markdown(f"🔹 **Analizando dominio:** [{check}]({check})")
    try:
        html = requests.get(check, headers=headers, timeout=10).text
        match = re.search(r"\$[0-9,]+", html)
        if match:
            val = float(match.group(0).replace("$", "").replace(",", ""))
            return val, val * 0.5
    except Exception:
        pass
    return None, None

# ================== FINTECH ==================
def simular_escrow(monto: float, dias: int):
    comision = monto * 0.035
    return monto, comision, monto - comision, dias

def simular_paypal_to_ach(monto: float):
    comision = monto * 0.08
    return monto, comision, monto - comision, "24 horas"

# ================== CÁLCULO BASE ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd:
        return None
    arr = np.array(precios_usd)
    mediana, promedio = np.median(arr), np.mean(arr)
    f_ant = max(0.3, 1 - 0.1 * antiguedad)
    f_cond = round(min(1, 0.4 + 0.6 * (condicion - 1) / 9), 2)
    f_riesgo = 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, valor=valor,
                factor_antiguedad=f_ant, factor_condicion=f_cond, factor_riesgo=f_riesgo)

# ================== IA PREMIUM (AVALÚO FINAL) ==================
def generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats):
    if not client:
        return "⚠️ IA Premium no disponible (falta OPENAI_API_KEY)."

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
- Valor base sugerido: {stats['valor']:.2f} USD

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
tipo = st.radio(
    "Selecciona una opción:",
    ["💻 Electrónica", "🟡 Prendas de Oro", "🌐 Activos Digitales", "💳 Custodia / PayPal"],
    horizontal=True,
)

if tipo == "💻 Electrónica":
    with st.sidebar:
        categoria = st.selectbox("Tipo de artículo", ["Laptop", "iPhone", "Consola", "Televisor", "Otro"])
        modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
        descripcion = st.text_area("Descripción", "Buen estado general, incluye accesorios.")
        precio_original = st.number_input("Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
        antiguedad = st.slider("Antigüedad (años)", 0, 10, 3)
        condicion = st.slider("Condición (1-10)", 1, 10, 7)
        st.subheader("🌐 Fuentes de datos")
        usar_ebay = st.checkbox("eBay", True)
        usar_google = st.checkbox("Google Shopping", False)
        usar_encuentra = st.checkbox("Encuentra24", False)
        usar_ia_sem = st.checkbox("IA semántica (precios sintéticos)", False)
        st.subheader("🤖 IA Premium")
        usar_ia_premium = st.checkbox("Activar IA Premium (simula $0.99)", False)

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

    # --- ELECTRÓNICA ---
    if tipo == "💻 Electrónica":
        query = construir_query(categoria, modelo)
        if not query:
            st.error("❌ Especifica al menos un modelo o categoría.")
        else:
            precios, resultados = [], []
            if usar_ebay:
                p, r = buscar_ebay_publico(query); precios += p; resultados += r
            if usar_google:
                p, r = buscar_google_shopping(query); precios += p; resultados += r
            if usar_encuentra:
                p, r = buscar_encuentra24(query); precios += p; resultados += r
            if usar_ia_sem:
                p, r = buscar_ia_semantica(query); precios += p; resultados += r

            if not precios:
                st.error("❌ No se encontraron precios.")
            else:
                df = pd.DataFrame(resultados)
                st.markdown("### 📊 Resultados de mercado combinados")
                st.dataframe(df, use_container_width=True, hide_index=True)

                stats = calcular_valor_empeno(precios, antiguedad, condicion)
                st.markdown("### 📈 Estadísticos y valor base de empeño")
                col1, col2, col3 = st.columns(3)
                col1.metric("💰 Mediana", f"${stats['mediana']:.2f}")
                col2.metric("📊 Promedio", f"${stats['promedio']:.2f}")
                col3.metric("💵 Valor de empeño sugerido", f"${stats['valor']:.2f}")
                st.info(
                    f"Antigüedad: {stats['factor_antiguedad']:.2f} | "
                    f"Condición: {stats['factor_condicion']:.2f} | "
                    f"Margen empeño: {stats['factor_riesgo']:.2f}"
                )

                chart = alt.Chart(pd.DataFrame({'Precio (USD)': precios})).mark_bar().encode(
                    alt.X('Precio (USD)', bin=alt.Bin(maxbins=20)),
                    alt.Y('count()', title='Frecuencia')
                ).properties(title="Distribución de precios de mercado")
                st.altair_chart(chart, use_container_width=True)

                # IA PREMIUM
                st.markdown("---")
                st.subheader("🤖 IA Premium (avalúo final)")
                if usar_ia_premium:
                    comentario = generar_comentario_ia(
                        query, descripcion, precio_original, antiguedad, condicion, stats
                    )
                    if "VALOR_RECOMENDADO_FINAL" in comentario:
                        try:
                            partes = comentario.split("VALOR_RECOMENDADO_FINAL:")[1]
                            valor_str = partes.split("-")[0].strip().replace("$", "").replace(",", "")
                            valor_str_clean = re.sub(r"[^\d.]", "", valor_str)
                            valor_ia = float(valor_str_clean)
                            justificacion = partes.split("-", 1)[1].strip()
                            st.success(f"**IA Premium sugiere:** ${valor_ia:,.2f} USD — *{justificacion}*")
                        except Exception as e:
                            st.warning(f"La IA respondió, pero no se pudo interpretar el valor: {comentario} (Error: {e})")
                    else:
                        st.warning(comentario)
                    st.caption("💳 Esta evaluación se considera una consulta premium simulada ($0.99).")
                else:
                    st.info("Activa la IA Premium en la barra lateral para una recomendación final con justificación.")

    # --- ORO ---
    elif tipo == "🟡 Prendas de Oro":
        bruto, empeño, precio_gramo = estimar_oro(peso, pureza, METALSDEV_API_KEY)
        st.metric("💰 Precio actual del oro (g)", f"${precio_gramo:.2f}")
        st.metric("💎 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor empeño sugerido", f"${empeño:,.2f}")

    # --- ACTIVOS DIGITALES ---
    elif tipo == "🌐 Activos Digitales":
        bruto, empeño = estimar_activo_digital(url)
        if bruto:
            st.metric("💻 Valor estimado", f"${bruto:,.2f}")
            st.metric("💵 Valor de empeño sugerido", f"${empeño:,.2f}")
        else:
            st.error("No se pudo estimar valor del dominio.")

    # --- FINTECH ---
    elif tipo == "💳 Custodia / PayPal":
        st.subheader("🔒 Simulador Escrow")
        monto_inicial, comision, neto, d = simular_escrow(monto, dias)
        st.success(f"💰 Monto: ${monto_inicial:.2f} | 💸 Comisión 3.5%: ${comision:.2f} | 🏦 Liberado: ${neto:.2f}")
        df1 = pd.DataFrame({'Concepto': ['Comisión', 'Monto liberado'], 'Valor': [comision, neto]})
        st.altair_chart(
            alt.Chart(df1).mark_arc(innerRadius=50).encode(theta='Valor', color='Concepto'),
            use_container_width=True
        )

        st.markdown("---")
        st.subheader("💳 Venta de saldo PayPal → ACH")
        dep, com_pp, neto_pp, tiempo = simular_paypal_to_ach(monto)
        st.success(f"📥 PayPal: ${dep:.2f} | 💸 Comisión 8%: ${com_pp:.2f} | 🏦 ACH: ${neto_pp:.2f} | ⏱️ {tiempo}")
        df2 = pd.DataFrame({'Concepto': ['Comisión', 'Transferencia neta'], 'Valor': [com_pp, neto_pp]})
        st.altair_chart(
            alt.Chart(df2).mark_arc(innerRadius=50).encode(theta='Valor', color='Concepto'),
            use_container_width=True
        )
