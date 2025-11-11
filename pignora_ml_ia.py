import re, requests, numpy as np, pandas as pd, feedparser, altair as alt, streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

# ================== CONFIGURACIÓN INICIAL ==================
OPENAI_API_KEY = None  # opcional, solo si tienes una
METALPRICE_API_KEY = "demo"  # clave pública y funcional sin registro
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
    except:
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
    except:
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
                        "Título": entry.title[:60]+"...",
                        "Precio USD": val,
                        "Link": entry.link
                    })
        return precios, resultados
    except:
        return [], []

# ================== IA SEMÁNTICA ==================
def buscar_ia_semantica(query: str):
    if not client:
        st.warning("⚠️ IA no disponible (sin API key).")
        return [], []
    prompt = f"Da 3 precios plausibles en USD para un artículo '{query}' usado."
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=50,
        )
        texto = resp.choices[0].message.content
        precios = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", texto) if 10 < float(x) < 10000]
        return precios, [{"Fuente": "IA", "Título": query, "Precio USD": p, "Link": "IA"} for p in precios]
    except Exception as e:
        st.warning(f"IA falló: {e}")
        return [], []

# ================== ORO (API EN TIEMPO REAL) ==================
def obtener_precio_oro_por_gramo(api_key: str) -> float:
    """Consulta el precio actual del oro por gramo (USD) con fallback."""
    try:
        url = f"https://api.metalpriceapi.com/v1/latest?api_key={api_key}&base=USD&currencies=XAU"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if "rates" in data and "XAU" in data["rates"]:
            precio_por_onza = data["rates"]["XAU"]
            precio_por_gramo = precio_por_onza / 31.1035
            return round(precio_por_gramo, 2)
        else:
            st.warning("⚠️ API oro sin datos válidos, usando 75 USD/g.")
            return 75.0
    except Exception as e:
        st.warning(f"⚠️ Error API oro: {e} — usando 75 USD/g.")
        return 75.0

def estimar_oro(peso_gramos: float, pureza: int, api_key: str):
    precio_oro_puro = obtener_precio_oro_por_gramo(api_key)
    factor_pureza = pureza / 24
    valor_bruto = peso_gramos * precio_oro_puro * factor_pureza
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2), precio_oro_puro

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
    f_ant, f_cond, f_riesgo = max(0.3, 1 - 0.1 * antiguedad), round(min(1, 0.4 + 0.6 * (condicion - 1) / 9), 2), 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, valor=valor)

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
tipo = st.radio("Selecciona una opción:",
                ["💻 Electrónica", "🟡 Prendas de Oro", "🌐 Activos Digitales", "💳 Custodia / PayPal"],
                horizontal=True)

if tipo == "💻 Electrónica":
    with st.sidebar:
        categoria = st.selectbox("Tipo de artículo", ["Laptop", "iPhone", "Consola", "Televisor", "Otro"])
        modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
        antiguedad = st.slider("Antigüedad (años)", 0, 10, 3)
        condicion = st.slider("Condición (1-10)", 1, 10, 7)
        usar_ebay = st.checkbox("eBay", True)
        usar_google = st.checkbox("Google Shopping", False)
        usar_encuentra = st.checkbox("Encuentra24", False)
        usar_ia = st.checkbox("IA Semántica", False)

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
        precios, resultados = [], []
        if usar_ebay: p, r = buscar_ebay_publico(query); precios += p; resultados += r
        if usar_google: p, r = buscar_google_shopping(query); precios += p; resultados += r
        if usar_encuentra: p, r = buscar_encuentra24(query); precios += p; resultados += r
        if usar_ia: p, r = buscar_ia_semantica(query); precios += p; resultados += r

        if not precios:
            st.error("❌ No se encontraron precios.")
        else:
            df = pd.DataFrame(resultados)
            st.dataframe(df, use_container_width=True, hide_index=True)
            stats = calcular_valor_empeno(precios, antiguedad, condicion)
            st.metric("💰 Mediana", f"${stats['mediana']:.2f}")
            st.metric("📊 Promedio", f"${stats['promedio']:.2f}")
            st.metric("💵 Valor de empeño sugerido", f"${stats['valor']:.2f}")
            chart = alt.Chart(pd.DataFrame({'Precio (USD)': precios})).mark_bar().encode(
                alt.X('Precio (USD)', bin=alt.Bin(maxbins=20)), alt.Y('count()'))
            st.altair_chart(chart, use_container_width=True)

    # --- ORO ---
    elif tipo == "🟡 Prendas de Oro":
        bruto, empeño, precio_gramo = estimar_oro(peso, pureza, METALPRICE_API_KEY)
        st.metric("💰 Precio actual del oro (g)", f"${precio_gramo:.2f}")
        st.metric("💎 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor empeño sugerido", f"${empeño:,.2f}")

    # --- DIGITAL ---
    elif tipo == "🌐 Activos Digitales":
        headers = {"User-Agent": "Mozilla/5.0"}
        site = url.replace("https://", "").replace("http://", "").split("/")[0]
        check = f"https://www.siteprice.org/website-worth/{site}"
        st.markdown(f"🔹 **Analizando dominio:** [{check}]({check})")
        try:
            html = requests.get(check, headers=headers, timeout=10).text
            match = re.search(r"\$[0-9,]+", html)
            if match:
                val = float(match.group(0).replace("$", "").replace(",", ""))
                st.metric("💻 Valor estimado", f"${val:,.2f}")
                st.metric("💵 Valor de empeño sugerido", f"${val*0.5:,.2f}")
            else:
                st.error("No se pudo estimar valor del dominio.")
        except:
            st.error("Error al conectar con el servicio de valoración.")

    # --- FINTECH ---
    elif tipo == "💳 Custodia / PayPal":
        st.subheader("🔒 Simulador Escrow")
        monto_inicial, comision, neto, d = simular_escrow(monto, dias)
        st.success(f"💰 Monto: ${monto_inicial:.2f} | 💸 Comisión 3.5%: ${comision:.2f} | 🏦 Liberado: ${neto:.2f}")
        df1 = pd.DataFrame({'Concepto': ['Comisión', 'Monto liberado'], 'Valor': [comision, neto]})
        st.altair_chart(alt.Chart(df1).mark_arc(innerRadius=50).encode(theta='Valor', color='Concepto'))

        st.markdown("---")
        st.subheader("💳 Venta de saldo PayPal → ACH")
        dep, com_pp, neto_pp, tiempo = simular_paypal_to_ach(monto)
        st.success(f"📥 PayPal: ${dep:.2f} | 💸 Comisión 8%: ${com_pp:.2f} | 🏦 ACH: ${neto_pp:.2f} | ⏱️ {tiempo}")
        df2 = pd.DataFrame({'Concepto': ['Comisión', 'Transferencia neta'], 'Valor': [com_pp, neto_pp]})
        st.altair_chart(alt.Chart(df2).mark_arc(innerRadius=50).encode(theta='Valor', color='Concepto'))
