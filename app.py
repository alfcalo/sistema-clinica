import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import numpy as np

# Configuración de la página
st.set_page_config(
    page_title="🏥 Sistema de Inventario Integrado",
    page_icon="🏥",
    layout="wide"
)

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    try:
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Usar secrets de Streamlit para deploy
        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=scope
        )
        
        client = gspread.authorize(credentials)
        return client.open('TESORERIA')
    except Exception as e:
        st.error(f"❌ Error de conexión: {str(e)}")
        st.stop()

# --- CARGA Y PROCESAMIENTO DE DATOS ---
@st.cache_data(ttl=600)
def cargar_y_procesar_datos():
    sh = conectar_google_sheets()
    
    # 1. Función auxiliar para leer hojas con manejo de errores
    def get_df(sheet_name):
        try:
            ws = sh.worksheet(sheet_name)
            data = ws.get_all_records()
            return pd.DataFrame(data)
        except Exception as e:
            st.warning(f"⚠️ No se pudo cargar la hoja '{sheet_name}': {e}")
            return pd.DataFrame()

    # Cargar Hojas Maestras
    df_farmacia_base = get_df("2.1_Productos")
    
    # Convertir IDs a string inmediatamente
    if not df_farmacia_base.empty and '2.1_ID' in df_farmacia_base.columns:
        df_farmacia_base['2.1_ID'] = df_farmacia_base['2.1_ID'].astype(str)
    
    # FILTRO 1: Solo procesar productos de grupo FARMACIA o CAFETIN
    if not df_farmacia_base.empty and '2.5_Grupo' in df_farmacia_base.columns:
        df_farmacia_base = df_farmacia_base[
            df_farmacia_base['2.5_Grupo'].isin(['FARMACIA', 'CAFETIN'])
        ]
    
    df_almacen_base = get_df("2.6_Almacen")
    if not df_almacen_base.empty and '2.6_ID' in df_almacen_base.columns:
        df_almacen_base['2.6_ID'] = df_almacen_base['2.6_ID'].astype(str)
    
    # FILTRO 2: Solo procesar productos de grupo FARMACIA o CAFETIN en Almacén
    if not df_almacen_base.empty and '2.6_Grupo' in df_almacen_base.columns:
        df_almacen_base = df_almacen_base[
            df_almacen_base['2.6_Grupo'].isin(['FARMACIA', 'CAFETIN'])
        ]
    
    # Cargar Hojas de Movimientos
    df_ventas = get_df("4.2_VentasDetalle")
    if not df_ventas.empty and '4.2_ProductoID' in df_ventas.columns:
        df_ventas['4.2_ProductoID'] = df_ventas['4.2_ProductoID'].astype(str)
    
    df_entradas_farma = get_df("2.4_EntradaProducto")
    if not df_entradas_farma.empty and '2.4_ProductoID' in df_entradas_farma.columns:
        df_entradas_farma['2.4_ProductoID'] = df_entradas_farma['2.4_ProductoID'].astype(str)
    
    df_devoluciones_alm = get_df("2.421_SalidaProducto")
    if not df_devoluciones_alm.empty and '2.421_ProductoID' in df_devoluciones_alm.columns:
        df_devoluciones_alm['2.421_ProductoID'] = df_devoluciones_alm['2.421_ProductoID'].astype(str)
    
    df_compras_alm = get_df("2.7_EntradaAlmacen")
    if not df_compras_alm.empty and '2.7_ProductoID' in df_compras_alm.columns:
        df_compras_alm['2.7_ProductoID'] = df_compras_alm['2.7_ProductoID'].astype(str)
    
    df_mermas_alm = get_df("2.61_SalidaAlmacen")
    if not df_mermas_alm.empty and '2.61_ProductoID' in df_mermas_alm.columns:
        df_mermas_alm['2.61_ProductoID'] = df_mermas_alm['2.61_ProductoID'].astype(str)

    # --- PROCESAMIENTO DE MOVIMIENTOS ---
    # Asegurar tipos numéricos y agrupar por ID
    def agrupar_mov(df, id_col, cant_col):
        if df.empty: return pd.DataFrame(columns=[id_col, cant_col])
        df[cant_col] = pd.to_numeric(df[cant_col], errors='coerce').fillna(0)
        return df.groupby(id_col)[cant_col].sum().reset_index()

    mov_ventas = agrupar_mov(df_ventas, '4.2_ProductoID', '4.2_Cantidad')
    mov_ent_farma = agrupar_mov(df_entradas_farma, '2.4_ProductoID', '2.4_Cantidad')
    mov_dev_alm = agrupar_mov(df_devoluciones_alm, '2.421_ProductoID', '2.421_Cantidad')
    mov_comp_alm = agrupar_mov(df_compras_alm, '2.7_ProductoID', '2.7_Cantidad')
    mov_merma_alm = agrupar_mov(df_mermas_alm, '2.61_ProductoID', '2.61_Cantidad')

    # --- CÁLCULO FARMACIA (PISO 1) ---
    df_farma = df_farmacia_base.copy()
    df_farma['2.1_Cantidad'] = pd.to_numeric(df_farma['2.1_Cantidad'], errors='coerce').fillna(0)
    
    # Merges para Farmacia
    df_farma = df_farma.merge(mov_ventas, left_on='2.1_ID', right_on='4.2_ProductoID', how='left')
    df_farma = df_farma.merge(mov_ent_farma, left_on='2.1_ID', right_on='2.4_ProductoID', how='left')
    df_farma = df_farma.merge(mov_dev_alm, left_on='2.1_ID', right_on='2.421_ProductoID', how='left')
    df_farma.fillna(0, inplace=True)

    # Fórmula: Inicial + Entradas - Devoluciones - Ventas
    df_farma['Stock_Real'] = (
        df_farma['2.1_Cantidad'] + 
        df_farma['2.4_Cantidad'] - 
        df_farma['2.421_Cantidad'] - 
        df_farma['4.2_Cantidad']
    )

    # --- CÁLCULO ALMACÉN (PISO 3) ---
    df_alm = df_almacen_base.copy()
    df_alm['2.6_Cantidad'] = pd.to_numeric(df_alm['2.6_Cantidad'], errors='coerce').fillna(0)

    # Merges para Almacén (reutilizamos movimientos ya calculados)
    df_alm = df_alm.merge(mov_comp_alm, left_on='2.6_ID', right_on='2.7_ProductoID', how='left')
    df_alm = df_alm.merge(mov_merma_alm, left_on='2.6_ID', right_on='2.61_ProductoID', how='left')
    df_alm = df_alm.merge(mov_ent_farma, left_on='2.6_ID', right_on='2.4_ProductoID', how='left')
    df_alm = df_alm.merge(mov_dev_alm, left_on='2.6_ID', right_on='2.421_ProductoID', how='left')
    df_alm.fillna(0, inplace=True)

    # Fórmula: Inicial + Compras - Mermas - Bajadas a Farma + Subidas de Farma
    df_alm['Stock_Real'] = (
        df_alm['2.6_Cantidad'] + 
        df_alm['2.7_Cantidad'] - 
        df_alm['2.61_Cantidad'] - 
        df_alm['2.4_Cantidad'] + 
        df_alm['2.421_Cantidad']
    )

    return df_farma, df_alm

# --- AUTENTICACIÓN ---
def check_password():
    """Retorna True si el usuario ingresó la contraseña correcta."""
    
    # Inicializar session state
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    
    # Si ya está autenticado, retornar True
    if st.session_state["authenticated"]:
        return True
    
    # Mostrar pantalla de login
    st.markdown("""
    <div style='text-align: center; padding: 50px;'>
        <h1>🏥 Sistema de Inventario - Clínica Ayacucho</h1>
        <p style='color: #666;'>Ingrese la contraseña para acceder al sistema</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Crear columnas para centrar el input
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        password = st.text_input(
            "Contraseña",
            type="password",
            key="password_input",
            placeholder="Ingrese la contraseña de acceso"
        )
        
        if st.button("🔓 Ingresar", use_container_width=True):
            if password == st.secrets["app_password"]:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta. Intente nuevamente.")
    
    st.markdown("---")
    st.caption("🔒 Sistema protegido - Solo personal autorizado")
    
    return False

# --- INTERFAZ USUARIO ---
def main():
    # Verificar autenticación ANTES de mostrar cualquier contenido
    if not check_password():
        st.stop()  # Detener ejecución si no está autenticado
    
    st.title("🏥 Sistema de Inventario Integrado (Farmacia & Almacén)")
    st.markdown("---")
    
    # FILTRO 2: Sidebar con slider para meses de anticipación de vencimiento
    st.sidebar.header("⚙️ Configuración")
    meses_vencimiento = st.sidebar.slider(
        "Meses de anticipación para alertas de vencimiento",
        min_value=1,
        max_value=12,
        value=3,
        help="Selecciona cuántos meses antes quieres ver las alertas de productos próximos a vencer"
    )
    dias_vencimiento = meses_vencimiento * 30  # Convertir meses a días aproximados

    with st.spinner("📦 Sincronizando datos con Google Sheets y calculando existencias..."):
        df_farma, df_alm = cargar_y_procesar_datos()

    tab1, tab2 = st.tabs(["💊 FARMACIA", "📦 ALMACÉN"])

    # --- PESTAÑA 1: FARMACIA ---
    with tab1:
        st.header("💊 Control de Existencias - Farmacia")
        
        # Métricas
        total_p_farma = len(df_farma)
        bajo_stock_farma = len(df_farma[df_farma['Stock_Real'] <= 5])
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Items en Farmacia", total_p_farma)
        m2.metric("Stock Crítico (≤5)", bajo_stock_farma, delta_color="inverse")
        m3.metric("Stock Total Real", f"{int(df_farma['Stock_Real'].sum()):,}")

        # Tabla con formato
        st.subheader("Listado de Productos en Farmacia")
        
        # Campo de búsqueda
        search_term = st.text_input(
            "🔍 Buscar por nombre o principio activo",
            placeholder="Ingrese el nombre del producto o principio activo...",
            key="search_farmacia"
        )
        
        # FILTRO: Solo mostrar productos con stock > 0
        df_farma_view = df_farma[
            df_farma['Stock_Real'] > 0
        ][[ 
            '2.1_ID', '2.1_Nombre', '2.1_PrincipioActivo', '2.1_Lote', '2.1_FechaVencimiento', 'Stock_Real'
        ]].copy()
        df_farma_view.columns = ['ID', 'Producto', 'Principio Activo', 'Lote', 'Vencimiento', 'Stock Real']
        
        # Convertir fecha de vencimiento a datetime para filtrado
        df_farma_view['Venc_Date'] = pd.to_datetime(df_farma_view['Vencimiento'], errors='coerce', dayfirst=True)
        hoy = pd.Timestamp.now().normalize()
        dias_vencimiento = meses_vencimiento * 30
        
        # Aplicar filtro de vencimiento (solo productos que vencen en el futuro dentro del rango)
        df_farma_view = df_farma_view[
            (df_farma_view['Venc_Date'] >= hoy) & 
            ((df_farma_view['Venc_Date'] - hoy).dt.days <= dias_vencimiento)
        ]
        
        # Eliminar la columna temporal Venc_Date antes de mostrar
        df_farma_view = df_farma_view.drop(columns=['Venc_Date'])
        
        # Aplicar filtro de búsqueda si hay texto ingresado
        if search_term:
            mask = (
                df_farma_view['Producto'].str.contains(search_term, case=False, na=False) |
                df_farma_view['Principio Activo'].str.contains(search_term, case=False, na=False)
            )
            df_farma_view = df_farma_view[mask]
        
        # Mostrar contador de resultados y botón de exportación
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"Mostrando {len(df_farma_view)} productos que vencen en los próximos {meses_vencimiento} meses")
        with col2:
            # Botón de exportación a CSV
            csv = df_farma_view.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Exportar CSV",
                data=csv,
                file_name=f"farmacia_productos_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        # Aplicar colores y alertas
        def color_stock(val):
            color = 'background-color: #ffcccc' if val <= 5 else ''
            return color

        st.dataframe(
            df_farma_view.style.applymap(color_stock, subset=['Stock Real']),
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.TextColumn("ID", help="ID del producto")
            }
        )


    # --- PESTAÑA 2: ALMACÉN ---
    with tab2:
        st.header("📦 Control de Existencias - Almacén")
        
        # Métricas
        total_p_alm = len(df_alm)
        bajo_stock_alm = len(df_alm[df_alm['Stock_Real'] <= 5])
        
        a1, a2, a3 = st.columns(3)
        a1.metric("Items en Almacén", total_p_alm)
        a2.metric("Stock Crítico (≤5)", bajo_stock_alm, delta_color="inverse")
        a3.metric("Stock Total Real", f"{int(df_alm['Stock_Real'].sum()):,}")

        # Tabla con formato
        st.subheader("Listado de Productos en Almacén")
        
        # FILTRO 3: Solo mostrar productos con stock > 0
        df_alm_view = df_alm[
            df_alm['Stock_Real'] > 0
        ][[
            '2.6_ID', '2.6_Nombre', '2.6_FechaVencimiento', 'Stock_Real'
        ]].copy()
        df_alm_view.columns = ['ID', 'Producto', 'Vencimiento', 'Stock Real']
        
        st.dataframe(
            df_alm_view.style.applymap(color_stock, subset=['Stock Real']),
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.TextColumn("ID", help="ID del producto")
            }
        )


if __name__ == "__main__":
    main()

