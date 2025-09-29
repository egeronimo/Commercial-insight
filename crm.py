# ----------------------------------------------------------
# IMPORTACION DE LIBRERIAS Y CONFIGURACION DE LA PAGINA
# ----------------------------------------------------------
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import numpy as np
from st_aggrid import AgGrid, GridOptionsBuilder
import requests
from io import BytesIO

# ----------------------------------------------------------
# FUNCIÓN PARA ORDENAR CÓDIGOS
# ----------------------------------------------------------
def ordenar_codigos_seguro(codigos):
    def clave_ordenacion(x):
        try:
            if isinstance(x, (int, float)):
                return (0, float(x))
            if str(x).replace('.', '', 1).isdigit():
                return (0, float(x))
            return (1, str(x).lower())
        except:
            return (1, str(x).lower())
    
    return sorted(codigos, key=clave_ordenacion)

# ----------------------------------------------------------
# CONFIGURACION DE LA PAGINA
# ----------------------------------------------------------

st.set_page_config(
    page_title="Commercial insight Dashboard",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------------------------------------------------
# Función para cargar datos desde Google Drive
# ----------------------------------------------------------
@st.cache_data
def load_data_from_drive(file_id):
    """Carga y procesa los datos desde Google Drive"""
    try:
        # Construir la URL de descarga directa para archivos de Google Sheets
        download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
        
        with st.spinner('Cargando datos...'):
            # Descargar el archivo
            response = requests.get(download_url)
            response.raise_for_status()  # Verificar que la descarga fue exitosa
            
            # Leer el archivo Excel
            excel_file = BytesIO(response.content)
            
            # Cargar las hojas de Excel
            pedidos = pd.read_excel(excel_file, sheet_name="pedido")
            entregas = pd.read_excel(excel_file, sheet_name="entregado")
            clientes = pd.read_excel(excel_file, sheet_name="clientes")
            
            # Limpieza de datos
            clientes["direccion"] = clientes["direccion"].astype(str).str.replace('"', '').str.strip()
            
            # Procesar pedidos
            pedidos["fecha_pedido"] = pd.to_datetime(pedidos["fecha_pedido"])
            pedidos["mes_pedido"] = pedidos["fecha_pedido"].dt.to_period('M')
            pedidos["monto"] = pedidos["cantidad"] * pedidos["precio_unitario"]
            
            # Procesar entregas
            entregas["fecha_entrega"] = pd.to_datetime(entregas["fecha_entrega"])
            entregas["mes_entrega"] = entregas["fecha_entrega"].dt.to_period('M')
            
            # Obtener fechas extremas para el pie de página
            fecha_min_pedidos = pedidos["fecha_pedido"].min().strftime('%d/%m/%Y') if not pedidos.empty else "N/A"
            fecha_max_pedidos = pedidos["fecha_pedido"].max().strftime('%d/%m/%Y') if not pedidos.empty else "N/A"
            fecha_min_entregas = entregas["fecha_entrega"].min().strftime('%d/%m/%Y') if not entregas.empty else "N/A"
            fecha_max_entregas = entregas["fecha_entrega"].max().strftime('%d/%m/%Y') if not entregas.empty else "N/A"
            
            # Agregación de pedidos por cliente
            pedidos_agg = pedidos.groupby("codigo_cliente").agg({
                "fecha_pedido": "max",
                "mes_pedido": lambda x: x.value_counts().index[0],
                "monto": ["sum", "mean"],
                "codigo_producto": "count"
            })
            pedidos_agg.columns = ['ultimo_pedido', 'mes_frecuente', 'monto_total', 'ticket_promedio', 'total_pedidos']
            pedidos_agg = pedidos_agg.reset_index()
            
            # Unir datos
            df = pd.merge(clientes, pedidos_agg, on="codigo_cliente", how="left").fillna(0)
            
            # CORRECCIÓN: Cálculo seguro de frecuencia de compra (días desde último pedido)
            hoy = pd.Timestamp.now().normalize()
            df["frecuencia_compra"] = (hoy - pd.to_datetime(df["ultimo_pedido"])).dt.days.fillna(0).astype(int)
            
            # CORRECCIÓN: Limitar frecuencia máxima a 365 días
            df["frecuencia_compra"] = df["frecuencia_compra"].clip(upper=365)
            
            # Calcular efectividad de entrega (pedidos vs entregas)
            entregas_count = entregas.groupby("codigo_cliente").size().reset_index(name='entregas_count')
            df = pd.merge(df, entregas_count, on="codigo_cliente", how="left").fillna(0)
            df["efectividad_entrega"] = (df["entregas_count"] / df["total_pedidos"].replace(0, 1)).clip(0, 1)
            
            # Segmentación automática
            df["segmento"] = pd.cut(
                df["frecuencia_compra"],
                bins=[-1, 30, 90, float('inf')],
                labels=["Activo", "Disminuido", "Inactivo"],
                right=False
            ).astype(str)
            
            # Valor del cliente (proyección anual)
            df["valor_cliente"] = (df["ticket_promedio"] * (365 / df["frecuencia_compra"].replace(0, 1))).round(2)
            
            # Productos top y bottom
            top_productos = (pedidos.groupby("producto")["cantidad"].sum()
                            .nlargest(5).reset_index().dropna())
            bottom_productos = (pedidos.groupby("producto")["cantidad"].sum()
                               .nsmallest(5).reset_index().dropna())
            
            return df, top_productos, bottom_productos, pedidos, entregas, fecha_min_pedidos, fecha_max_pedidos, fecha_min_entregas, fecha_max_entregas
        
    except Exception as e:
        st.error(f"Error al cargar los datos: {str(e)}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "N/A", "N/A", "N/A", "N/A"

# ----------------------------------------------------------
# CARGAR DATOS DESDE GOOGLE DRIVE
# ----------------------------------------------------------

# ID del archivo en Google Drive (extraído de la URL compartida)
# URL proporcionada: https://docs.google.com/spreadsheets/d/1MLgtcblazoKbx0ZwiPljCQxix5bTuKBn/edit?usp=sharing&ouid=117295945155119200843&rtpof=true&sd=true
FILE_ID = "1MLgtcblazoKbx0ZwiPljCQxix5bTuKBn"

# Cargar datos
df, top_productos, bottom_productos, pedidos, entregas, fecha_min_p, fecha_max_p, fecha_min_e, fecha_max_e = load_data_from_drive(FILE_ID)

if df.empty:
    st.warning("No se encontraron datos o hubo un error al cargarlos. Verifica con el administrador.")
    st.stop()

# Sidebar - Filtros
st.sidebar.header("🔍 Filtros Avanzados")
with st.sidebar.expander("Explicación de los filtros"):
    st.write("""
    - **Vendedor (Zona):** Filtra clientes por zona geográfica o vendedor asignado
    - **Segmento:** Clasificación automática según frecuencia de compra
    - **Mes:** Filtra por mes específico de actividad
    """)

# Opciones de filtros
df['zona'] = df.get('zona', 'No especificada').astype(str)
df['segmento'] = df.get('segmento', 'No especificado').astype(str)

# Filtro por mes (convertir a string para evitar problemas)
if not pedidos.empty:
    meses_disponibles = pedidos["mes_pedido"].astype(str).unique()
else:
    meses_disponibles = []

selected_vendedor = st.sidebar.selectbox(
    "Vendedor (Zona)",
    options=["Todos"] + sorted(df["zona"].unique().tolist(), key=str)
)

selected_segmento = st.sidebar.selectbox(
    "Segmento",
    options=["Todos"] + sorted(df["segmento"].unique().tolist(), key=str),
    help="Clasificación basada en frecuencia de compra: Activo (<30 días), Disminuido (30-90 días), Inactivo (>90 días)"
)

selected_mes = st.sidebar.selectbox(
    "Mes",
    options=["Todos"] + sorted(meses_disponibles.tolist()),
    help="Filtrar por mes de actividad"
)

# Filtrado de datos
filtered_df = df.copy()
if selected_vendedor != "Todos":
    filtered_df = filtered_df[filtered_df["zona"] == selected_vendedor]
if selected_segmento != "Todos":
    filtered_df = filtered_df[filtered_df["segmento"] == selected_segmento]
if selected_mes != "Todos":
    filtered_df = filtered_df[filtered_df["mes_frecuente"].astype(str) == selected_mes]

# Pestañas principales - INTERCAMBIADAS: Ahora Analítica es primero
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Analítica", "📞 Clientes", "👤 Vendedores", "🔥 Promociones", "🚨 Alertas"])

# ----------------------------------------------------------
# PESTAÑA 1: Analítica Comercial
# ----------------------------------------------------------
with tab1:
    st.header("📊 Analítica Comercial", help="Métricas y visualizaciones para toma de decisiones")
    
    if not filtered_df.empty:
        # KPIs generales con explicación
        st.subheader("📈 Indicadores Clave")
        with st.expander("ℹ️ Explicación de los KPIs"):
            st.write("""
            - **Clientes totales:** Número único de clientes activos
            - **Compra promedio:** Valor promedio de los pedidos
            - **Frecuencia promedio:** Días entre compras (menos es mejor)
            - **Valor cliente:** Proyección anual de gasto del cliente
            """)
        
        metric_cols = st.columns(4)
        with metric_cols[0]:
            st.metric("Clientes totales", filtered_df["codigo_cliente"].nunique())
        with metric_cols[1]:
            st.metric("Compra promedio", f"${filtered_df['monto_total'].mean():,.2f}")
        with metric_cols[2]:
            st.metric("Frecuencia promedio", f"{filtered_df['frecuencia_compra'].mean():.0f} días")
        with metric_cols[3]:
            st.metric("Valor cliente promedio", f"${filtered_df['valor_cliente'].mean():,.2f}")
        
        # Segmentación de clientes
        st.subheader("🔍 Segmentación de Clientes")
        with st.expander("📌 Cómo se calculan los segmentos"):
            st.write("""
            Los clientes se clasifican automáticamente según días desde su última compra:
            - **Activo:** <30 días
            - **Disminuido:** 30-90 días
            - **Inactivo:** >90 días
            """)
        
        seg_cols = st.columns(2)
        with seg_cols[0]:
            fig = px.pie(filtered_df, names="segmento", title="Distribución por Segmento")
            st.plotly_chart(fig, use_container_width=True)
        with seg_cols[1]:
            fig = px.bar(
                filtered_df.groupby("segmento").agg({"monto_total": "sum", "codigo_cliente": "nunique"}).reset_index(),
                x="segmento",
                y=["monto_total", "codigo_cliente"],
                barmode="group",
                title="Ventas vs Cantidad de Clientes",
                labels={"value": "Cantidad", "variable": "Métrica"}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Productos más y menos vendidos
        st.subheader("📦 Análisis de Productos")
        with st.expander("ℹ️ Fuente de datos"):
            st.write("""
            Datos calculados a partir del historial completo de pedidos.
            Los productos se ponderan por cantidad vendida.
            """)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🏆 Top 5 Productos**")
            st.dataframe(top_productos, hide_index=True)
        with col2:
            st.markdown("**📉 Bottom 5 Productos**")
            st.dataframe(bottom_productos, hide_index=True)
        
        # Mapa de calor geográfico
        st.subheader("🗺️ Distribución Geográfica")
        with st.expander("ℹ️ Interpretación del mapa"):
            st.write("""
            Los puntos más intensos muestran zonas con mayor concentración de ventas.
            Use este mapa para:
            - Identificar zonas con potencial de crecimiento
            - Optimizar rutas de reparto
            - Planificar campañas geolocalizadas
            """)
        
        # Asegurar coordenadas
        if "lat" not in filtered_df.columns or "lon" not in filtered_df.columns:
            filtered_df["lat"] = 18.5  # RD centro
            filtered_df["lon"] = -69.9
        
        fig = px.density_mapbox(
            filtered_df,
            lat="lat",
            lon="lon",
            z="monto_total",
            radius=20,
            zoom=7,
            mapbox_style="open-street-map",
            hover_name="nombre",
            hover_data=["segmento", "valor_cliente"],
            title="Concentración de Ventas por Zona"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 2: Gestión de Clientes
# ----------------------------------------------------------
with tab2:
    st.header("📞 Gestión de Clientes")
    
    if not filtered_df.empty:
        # BÚSQUEDA MEJORADA: Por código O nombre
        col_busqueda1, col_busqueda2 = st.columns(2)
        
        with col_busqueda1:
            # Obtener códigos únicos y manejar nulos
            codigos_unicos = filtered_df["codigo_cliente"].dropna().unique()
            codigos_options = [""] + ordenar_codigos_seguro([str(cod) for cod in codigos_unicos])
            
            cliente_search_code = st.selectbox(
                "Buscar por CÓDIGO del cliente",
                options=codigos_options,
                format_func=lambda x: "Seleccione un código..." if x == "" else x,
                key="cliente_search_code"  # Key único para evitar conflicto
            )
        
        with col_busqueda2:
            # Obtener nombres únicos
            nombres_unicos = filtered_df["nombre"].dropna().unique()
            nombres_options = [""] + sorted([str(nombre) for nombre in nombres_unicos])
            
            cliente_search_name = st.selectbox(
                "Buscar por NOMBRE del cliente",
                options=nombres_options,
                format_func=lambda x: "Seleccione un nombre..." if x == "" else x,
                key="cliente_search_name"  # Key único para evitar conflicto
            )
        
        # Proceso de búsqueda mejorado
        cliente_filtrado = pd.DataFrame()
        
        if cliente_search_code and cliente_search_code != "":
            try:
                cliente_filtrado = filtered_df[filtered_df["codigo_cliente"].astype(str) == cliente_search_code]
            except Exception as e:
                st.error(f"Error en búsqueda por código: {str(e)}")
        
        elif cliente_search_name and cliente_search_name != "":
            try:
                # Búsqueda flexible por nombre (contiene el texto)
                cliente_filtrado = filtered_df[filtered_df["nombre"].str.contains(cliente_search_name, case=False, na=False)]
            except Exception as e:
                st.error(f"Error en búsqueda por nombre: {str(e)}")
        
        # Mostrar resultados de búsqueda
        if not cliente_filtrado.empty:
            if len(cliente_filtrado) > 1:
                st.info(f"Se encontraron {len(cliente_filtrado)} clientes. Mostrando el primero.")
            
            cliente_data = cliente_filtrado.iloc[0]
            
            # Mostrar datos básicos
            cols = st.columns(3)
            with cols[0]:
                st.info(f"**Nombre:** {cliente_data['nombre']}")
                st.info(f"**Código:** {cliente_data['codigo_cliente']}")
                st.info(f"**Teléfono:** {cliente_data['telefono']}")
            with cols[1]:
                st.info(f"**Dirección:** {cliente_data['direccion']}")
                st.info(f"**Tipo negocio:** {cliente_data['tipo_negocio']}")
            with cols[2]:
                st.info(f"**Quién atiende:** {cliente_data['quien_atiende']}")
                st.info(f"**Vendedor (Zona):** {cliente_data['zona']}")
            
            # Mostrar KPIs con formato mejorado
            st.subheader("📊 Indicadores Clave")
            kpi_cols = st.columns(4)
            with kpi_cols[0]:
                st.metric("Ticket promedio", f"RD${cliente_data['ticket_promedio']:,.2f}")
            with kpi_cols[1]:
                st.metric("Frecuencia compra", f"{cliente_data['frecuencia_compra']:,.0f} días")
            with kpi_cols[2]:
                st.metric("Efectividad entrega", f"{cliente_data['efectividad_entrega']:.2%}")
            with kpi_cols[3]:
                estado_color = {"Activo": "normal", "Disminuido": "off", "Inactivo": "inverse"}.get(cliente_data["segmento"], "off")
                st.metric("Segmento", cliente_data["segmento"], delta_color=estado_color)
                      
            # SECCIÓN DE ANÁLISIS DE PRODUCTOS MEJORADA
            st.subheader("🍅 Análisis de Productos", help="Datos históricos de compras y recomendaciones")
            
            # Productos del cliente
            productos_cliente = pedidos[pedidos['codigo_cliente'] == cliente_data['codigo_cliente']]
            
            # Top productos del cliente (con monto total)
            top_productos_cliente = productos_cliente.groupby('producto').agg({
                'cantidad': 'sum',
                'monto': 'sum'
            }).nlargest(5, 'cantidad').reset_index()
            top_productos_cliente['monto_formateado'] = top_productos_cliente['monto'].apply(lambda x: f"RD${x:,.2f}")
            
            # Productos recomendados (basado en clientes similares) con montos
            with st.expander("🔍 Método de recomendación"):
                st.write("""
                Los productos recomendados se calculan basándose en:
                1. Clientes con mismo tipo de negocio y zona
                2. Productos más vendidos entre ese grupo
                3. Productos que este cliente no compra actualmente
                4. Monto total en ventas de cada producto
                """)
            
            clientes_similares = filtered_df[
                (filtered_df['tipo_negocio'] == cliente_data['tipo_negocio']) & 
                (filtered_df['zona'] == cliente_data['zona'])
            ]
            
            productos_recomendados = pedidos[
                pedidos['codigo_cliente'].isin(clientes_similares['codigo_cliente'])
            ].groupby('producto').agg({
                'cantidad': 'sum',
                'monto': 'sum'
            }).nlargest(5, 'cantidad').reset_index()
            productos_recomendados['monto_formateado'] = productos_recomendados['monto'].apply(lambda x: f"RD${x:,.2f}")
            
            # Productos no comprados (oportunidades) con precios de referencia
            todos_productos = pedidos['producto'].unique()
            productos_no_comprados = [p for p in todos_productos if p not in productos_cliente['producto'].unique()]
            
            # Obtener precios de referencia para productos no comprados
            oportunidades_data = []
            for producto in productos_no_comprados[:5]:  # Solo primeros 5
                precio_referencia = pedidos[pedidos['producto'] == producto]['precio_unitario'].mean()
                oportunidades_data.append({
                    'producto': producto,
                    'precio_referencia': f"RD${precio_referencia:,.2f}" if not pd.isna(precio_referencia) else "N/A"
                })
            oportunidades_df = pd.DataFrame(oportunidades_data)
            
            # Mostrar en 3 columnas con formato mejorado
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**📦 Productos que más compra**")
                # Crear tabla formateada
                display_top = top_productos_cliente[['producto', 'cantidad', 'monto_formateado']].copy()
                display_top.columns = ['Producto', 'Cantidad', 'Monto Total']
                st.dataframe(
                    display_top.style.format({
                        'Cantidad': '{:,.0f}',
                        'Monto Total': '{}'
                    }), 
                    hide_index=True,
                    use_container_width=True
                )
                
            with col2:
                st.markdown("**💡 Recomendados para su negocio**")
                # Crear tabla formateada
                display_recomendados = productos_recomendados[['producto', 'cantidad', 'monto_formateado']].copy()
                display_recomendados.columns = ['Producto', 'Cantidad', 'Monto Total']
                st.dataframe(
                    display_recomendados.style.format({
                        'Cantidad': '{:,.0f}',
                        'Monto Total': '{}'
                    }), 
                    hide_index=True,
                    use_container_width=True
                )
                
            with col3:
                st.markdown("**🚀 Oportunidades de venta**")
                if not oportunidades_df.empty:
                    st.dataframe(
                        oportunidades_df.rename(columns={
                            'producto': 'Producto', 
                            'precio_referencia': 'Precio Referencia'
                        }), 
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.write("No hay oportunidades identificadas")
            
            # GUÍA DE CONVERSACIÓN COMERCIAL
            st.subheader("💬 Guía de Ventas", help="Estrategias según perfil del cliente")
            
            # Explicación del segmento
            with st.expander(f"📌 Explicación del segmento: {cliente_data['segmento']}"):
                if cliente_data['segmento'] == "Activo":
                    st.write("""
                    **Cliente ACTIVO:** Realiza compras frecuentes (última compra hace menos de 30 días)
                    - Estrategia: Fidelización y venta cruzada
                    - Objetivo: Aumentar ticket promedio
                    """)
                elif cliente_data['segmento'] == "Disminuido":
                    st.write("""
                    **Cliente DISMINUIDO:** Frecuencia de compra reducida (última compra hace 30-90 días)
                    - Estrategia: Reactivación
                    - Objetivo: Recuperar frecuencia histórica
                    """)
                else:
                    st.write("""
                    **Cliente INACTIVO:** Sin compras recientes (última compra hace más de 90 días)
                    - Estrategia: Recuperación
                    - Objetivo: Primera compra
                    """)
            
            # Discurso recomendado
            if cliente_data['segmento'] == "Activo":
                st.success("**Discurso recomendado para cliente ACTIVO:**")
                st.write(f"""
                "Don/Dña {cliente_data['nombre'].split()[0]}, siempre es un placer atenderle. 
                Como veo que frecuenta nuestro colmado, quería comentarle sobre **{productos_recomendados.iloc[0]['producto']}** 
                que está teniendo mucha aceptación. ¿Le interesaría probar una muestra o llevar una cantidad pequeña 
                con un **5% de descuento** por ser cliente preferencial?"
                """)
                
            elif cliente_data['segmento'] == "Disminuido":
                st.warning("**Discurso recomendado para cliente DISMINUIDO:**")
                st.write(f"""
                "Don/Dña {cliente_data['nombre'].split()[0]}, ¡cuánto tiempo sin atenderle! 
                Hemos notado que antes solía comprar **{top_productos_cliente.iloc[0]['producto']}** con frecuencia. 
                Tenemos una **oferta especial** solo para usted este mes. ¿Quiere que le aparte algunas unidades 
                con un **10% de descuento** para que vuelva a disfrutar de nuestros productos?"
                """)
                
            else:
                st.error("**Discurso recomendado para cliente INACTIVO:**")
                st.write(f"""
                "Don/Dña {cliente_data['nombre'].split()[0]}, espero que esté bien. 
                Nos hacía falta su visita y queríamos ofrecerle un **descuento especial del 15%** 
                en su próxima compra más **entrega gratuita**. ¿Qué productos necesita actualmente 
                para su negocio? Tenemos disponibilidad de **{productos_recomendados.iloc[0]['producto']}** 
                que podría interesarle."
                """)
            
            # Frecuencia de contacto recomendada
            st.markdown("**⏰ Frecuencia recomendada de contacto:**")
            if cliente_data['frecuencia_compra'] < 15:
                st.write("- Cada 2 semanas (cliente muy activo)")
            elif cliente_data['frecuencia_compra'] < 30:
                st.write("- Semanal (mantener engagement)")
            else:
                st.write("- 2-3 veces por semana (recuperación urgente)")
            
            # BOTÓN PARA LIMPIAR BÚSQUEDA Y VOLVER AL INICIO
            st.markdown("---")
            if st.button("🔄 Limpiar búsqueda y volver al listado", type="secondary"):
                # Usamos session state para resetear los selectboxes
                st.session_state.cliente_search_code = ""
                st.session_state.cliente_search_name = ""
                st.rerun()
            
        else:
            if cliente_search_code or cliente_search_name:
                st.warning("No se encontraron clientes con los criterios de búsqueda")
                # Botón para limpiar búsqueda
                if st.button("🔄 Limpiar búsqueda", type="secondary"):
                    st.session_state.cliente_search_code = ""
                    st.session_state.cliente_search_name = ""
                    st.rerun()
            else:
                st.info("Use los filtros de búsqueda para encontrar un cliente específico")
                
                # Mostrar lista resumida de clientes disponibles
                with st.expander("👥 Ver lista de clientes disponibles"):
                    clientes_resumen = filtered_df[['codigo_cliente', 'nombre', 'segmento', 'zona']].head(10)
                    st.dataframe(
                        clientes_resumen.style.format({
                            'codigo_cliente': '{}'
                        }), 
                        hide_index=True,
                        use_container_width=True
                    )
                    if len(filtered_df) > 10:
                        st.caption(f"Mostrando 10 de {len(filtered_df)} clientes. Use la búsqueda para encontrar clientes específicos.")
    else:
        st.warning("No hay clientes que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 3: Desempeño de Vendedores
# ----------------------------------------------------------
with tab3:
    st.header("👤 Desempeño de Vendedores", help="Métricas y análisis por vendedor/zona")
    
    if not filtered_df.empty:
        # Selección de vendedor específico para análisis detallado
        vendedores_disponibles = ["Todos"] + sorted(filtered_df["zona"].unique().tolist())
        vendedor_seleccionado = st.selectbox(
            "Seleccionar Vendedor para Análisis Detallado",
            options=vendedores_disponibles,
            help="Seleccione un vendedor para ver análisis específico",
            key="vendedor_seleccionado"
        )
        
        # Filtrar datos si se selecciona un vendedor específico
        df_vendedor = filtered_df if vendedor_seleccionado == "Todos" else filtered_df[filtered_df["zona"] == vendedor_seleccionado]
        
        if vendedor_seleccionado != "Todos":
            st.subheader(f"📊 Análisis Detallado: {vendedor_seleccionado}")
            
            # KPIs del vendedor con formato mejorado
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Clientes", f"{df_vendedor['codigo_cliente'].nunique():,}")
            with col2:
                st.metric("Ventas Totales", f"RD${df_vendedor['monto_total'].sum():,.2f}")
            with col3:
                st.metric("Ticket Promedio", f"RD${df_vendedor['ticket_promedio'].mean():,.2f}")
            with col4:
                st.metric("Efectividad", f"{df_vendedor['efectividad_entrega'].mean():.2%}")
            
            # Productos que más vende el vendedor con formato
            st.subheader("📦 Productos que Más Vende")
            if not pedidos.empty:
                productos_vendedor = pedidos[pedidos['codigo_cliente'].isin(df_vendedor['codigo_cliente'])]
                top_productos_vendedor = productos_vendedor.groupby('producto').agg({
                    'cantidad': 'sum',
                    'monto': 'sum'
                }).nlargest(10, 'cantidad').reset_index()
                
                # Formatear montos para display
                top_productos_vendedor['monto_formateado'] = top_productos_vendedor['monto'].apply(lambda x: f"RD${x:,.2f}")
                top_productos_vendedor['cantidad_formateada'] = top_productos_vendedor['cantidad'].apply(lambda x: f"{x:,.0f}")
                
                fig_productos = px.bar(
                    top_productos_vendedor,
                    x='producto',
                    y='cantidad',
                    title=f"Top 10 Productos - {vendedor_seleccionado}",
                    labels={'cantidad': 'Cantidad Vendida', 'producto': 'Producto'},
                    hover_data={'monto': ':.2f'}
                )
                # Mejorar formato del tooltip
                fig_productos.update_traces(
                    hovertemplate="<br>".join([
                        "Producto: %{x}",
                        "Cantidad: %{y:,}",
                        "Monto Total: RD$%{customdata[0]:,.2f}"
                    ]),
                    customdata=top_productos_vendedor[['monto']]
                )
                st.plotly_chart(fig_productos, use_container_width=True)
                
                # Mostrar tabla detallada
                with st.expander("📋 Ver tabla detallada de productos"):
                    display_productos = top_productos_vendedor[['producto', 'cantidad', 'monto_formateado']].copy()
                    display_productos.columns = ['Producto', 'Cantidad', 'Monto Total']
                    st.dataframe(
                        display_productos.style.format({
                            'Cantidad': '{:,.0f}'
                        }), 
                        hide_index=True,
                        use_container_width=True
                    )
            
            # Segmentación de clientes del vendedor
            st.subheader("🔍 Segmentación de Clientes")
            seg_vendedor_cols = st.columns(2)
            with seg_vendedor_cols[0]:
                fig_segmento = px.pie(
                    df_vendedor, 
                    names="segmento", 
                    title=f"Segmentación - {vendedor_seleccionado}",
                    hole=0.4
                )
                st.plotly_chart(fig_segmento, use_container_width=True)
            
            with seg_vendedor_cols[1]:
                # Oportunidades: clientes inactivos que podrían reactivarse
                clientes_inactivos = df_vendedor[df_vendedor["segmento"] == "Inactivo"]
                st.metric("Clientes Inactivos", f"{len(clientes_inactivos):,}")
                if len(clientes_inactivos) > 0:
                    with st.expander("📋 Ver clientes inactivos"):
                        display_inactivos = clientes_inactivos[['nombre', 'codigo_cliente', 'frecuencia_compra', 'monto_total']].copy()
                        display_inactivos['monto_total_formateado'] = display_inactivos['monto_total'].apply(lambda x: f"RD${x:,.2f}")
                        display_inactivos['frecuencia_compra_formateada'] = display_inactivos['frecuencia_compra'].apply(lambda x: f"{x:,} días")
                        
                        st.dataframe(
                            display_inactivos[['nombre', 'codigo_cliente', 'frecuencia_compra_formateada', 'monto_total_formateado']].rename(columns={
                                'nombre': 'Nombre',
                                'codigo_cliente': 'Código',
                                'frecuencia_compra_formateada': 'Días sin Compra',
                                'monto_total_formateado': 'Histórico Ventas'
                            }), 
                            hide_index=True,
                            use_container_width=True
                        )
        
        # Estadísticas generales por vendedor (tabla comparativa) CON FORMATO MEJORADO
        st.subheader("📋 Comparativa de Vendedores")
        
        # Calcular estadísticas con formato
        vendedor_stats = filtered_df.groupby("zona").agg({
            "nombre": "count",
            "frecuencia_compra": "mean",
            "efectividad_entrega": "mean",
            "ticket_promedio": "mean",
            "valor_cliente": "mean",
            "monto_total": "sum"
        }).reset_index()

        # Aplicar formato a las métricas
        vendedor_stats["clientes_formateado"] = vendedor_stats["nombre"].apply(lambda x: f"{x:,.0f}")
        vendedor_stats["frecuencia_formateada"] = vendedor_stats["frecuencia_compra"].round(0).apply(lambda x: f"{x:,.0f}")
        vendedor_stats["efectividad_formateada"] = (vendedor_stats["efectividad_entrega"] * 100).round(2).apply(lambda x: f"{x:.2f}%")
        vendedor_stats["ticket_formateado"] = vendedor_stats["ticket_promedio"].round(2).apply(lambda x: f"RD${x:,.2f}")
        vendedor_stats["valor_cliente_formateado"] = vendedor_stats["valor_cliente"].round(2).apply(lambda x: f"RD${x:,.2f}")
        vendedor_stats["monto_total_formateado"] = vendedor_stats["monto_total"].round(2).apply(lambda x: f"RD${x:,.2f}")

        # Configuración de AgGrid con formato mejorado
        gb = GridOptionsBuilder.from_dataframe(
            vendedor_stats[[
                "zona", "clientes_formateado", "frecuencia_formateada", 
                "efectividad_formateada", "ticket_formateado", 
                "valor_cliente_formateado", "monto_total_formateado"
            ]]
        )
        
        gb.configure_column("zona", 
                          header_name="Vendedor/Zona", 
                          width=150,
                          tooltipField="Vendedor/Zona")
        
        gb.configure_column("clientes_formateado", 
                          header_name="Clientes",
                          width=100,
                          type=["numericColumn"],
                          tooltipField="Clientes",
                          headerTooltip="Número total de clientes únicos")
        
        gb.configure_column("frecuencia_formateada", 
                          header_name="Frecuencia (días)",
                          width=130,
                          tooltipField="Frecuencia (días)",
                          headerTooltip="Días promedio entre compras")
        
        gb.configure_column("efectividad_formateada", 
                          header_name="Efectividad",
                          width=120,
                          tooltipField="Efectividad",
                          headerTooltip="Porcentaje de pedidos entregados exitosamente")
        
        gb.configure_column("ticket_formateado", 
                          header_name="Ticket Promedio",
                          width=140,
                          tooltipField="Ticket Promedio",
                          headerTooltip="Valor promedio de cada pedido")
        
        gb.configure_column("valor_cliente_formateado", 
                          header_name="Valor Cliente",
                          width=140,
                          tooltipField="Valor Cliente",
                          headerTooltip="Proyección anual de gasto del cliente")
        
        gb.configure_column("monto_total_formateado", 
                          header_name="Ventas Totales",
                          width=140,
                          tooltipField="Ventas Totales",
                          headerTooltip="Ventas acumuladas en el período")

        grid_options = gb.build()
        
        AgGrid(
            vendedor_stats[[
                "zona", "clientes_formateado", "frecuencia_formateada", 
                "efectividad_formateada", "ticket_formateado", 
                "valor_cliente_formateado", "monto_total_formateado"
            ]],
            gridOptions=grid_options,
            theme="alpine",
            enable_enterprise_modules=False,
            fit_columns_on_grid_load=True,
            height=400
        )
        
        # Gráfico comparativo con formato mejorado
        st.subheader("📈 Comparativa Visual de Desempeño")
        
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            fig_ventas = px.bar(
                vendedor_stats,
                x="zona",
                y="monto_total",
                title="Ventas Totales por Vendedor",
                labels={"monto_total": "Ventas Totales (RD$)", "zona": "Vendedor/Zona"},
                color="monto_total",
                color_continuous_scale="Viridis"
            )
            fig_ventas.update_layout(
                yaxis=dict(
                    tickformat=",",
                    title="Ventas Totales (RD$)"
                )
            )
            fig_ventas.update_traces(
                hovertemplate="<br>".join([
                    "Vendedor: %{x}",
                    "Ventas Totales: RD$%{y:,.2f}"
                ])
            )
            st.plotly_chart(fig_ventas, use_container_width=True)
        
        with col_chart2:
            fig_clientes = px.bar(
                vendedor_stats,
                x="zona",
                y="nombre",
                title="Cantidad de Clientes por Vendedor",
                labels={"nombre": "Número de Clientes", "zona": "Vendedor/Zona"},
                color="nombre",
                color_continuous_scale="Blues"
            )
            fig_clientes.update_layout(
                yaxis=dict(
                    tickformat=",",
                    title="Número de Clientes"
                )
            )
            fig_clientes.update_traces(
                hovertemplate="<br>".join([
                    "Vendedor: %{x}",
                    "Clientes: %{y:,}"
                ])
            )
            st.plotly_chart(fig_clientes, use_container_width=True)
        
        # Resumen ejecutivo
        if vendedor_seleccionado != "Todos":
            st.subheader("🎯 Resumen Ejecutivo")
            
            # Calcular algunas métricas comparativas
            promedio_industria_efectividad = 0.85  # 85% como referencia
            promedio_industria_frecuencia = 45  # 45 días como referencia
            
            efectividad_vendedor = df_vendedor['efectividad_entrega'].mean()
            frecuencia_vendedor = df_vendedor['frecuencia_compra'].mean()
            
            col_res1, col_res2, col_res3 = st.columns(3)
            
            with col_res1:
                if efectividad_vendedor > promedio_industria_efectividad:
                    st.success(f"✅ Efectividad: **{efectividad_vendedor:.2%}** (Supera referencia)")
                else:
                    st.warning(f"⚠️ Efectividad: **{efectividad_vendedor:.2%}** (Por debajo de referencia)")
            
            with col_res2:
                if frecuencia_vendedor < promedio_industria_frecuencia:
                    st.success(f"✅ Frecuencia: **{frecuencia_vendedor:,.0f} días** (Mejor que referencia)")
                else:
                    st.warning(f"⚠️ Frecuencia: **{frecuencia_vendedor:,.0f} días** (Mayor que referencia)")
            
            with col_res3:
                clientes_activos = len(df_vendedor[df_vendedor['segmento'] == 'Activo'])
                porcentaje_activos = (clientes_activos / len(df_vendedor)) * 100
                st.info(f"📊 Clientes Activos: **{clientes_activos:,}** ({porcentaje_activos:.1f}%)")
        
    else:
        st.warning("No hay datos de vendedores que coincidan con los filtros seleccionados")

# ----------------------------------------------------------
# PESTAÑA 4: ESTRATEGIAS DE PROMOCIÓN
# ----------------------------------------------------------
with tab4:
    st.header("🔥 Estrategias de Promoción", help="Generador de promociones por segmento")
    
    # Promociones por segmento
    st.subheader("🎯 Promociones Segmentadas")
    with st.expander("ℹ️ Cómo usar estas promociones"):
        st.write("""
        Las promociones se generan automáticamente según el perfil del cliente:
        - **Activos:** Programas de fidelización
        - **Disminuidos:** Ofertas de reactivación
        - **Inactivos:** Descuentos agresivos
        """)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**🟢 Para clientes ACTIVOS**")
        st.write("- Programa de puntos (1% cashback)")
        st.write("- Muestras gratis con compras >$5,000")
        st.write("- Descuento del 5% en productos nuevos")
        
    with col2:
        st.markdown("🟡 **Para clientes DISMINUIDOS**")
        st.write("- 10% descuento en pedidos recurrentes")
        st.write("- Envío gratis en próxima compra")
        st.write("- Regalo sorpresa al alcanzar meta")
        
    with col3:
        st.markdown("🔴 **Para clientes INACTIVOS**")
        st.write("- 15% descuento en primera compra")
        st.write("- Entrega express sin costo")
        st.write("- Kit de bienvenida al volver")
    
    # Generador de promociones
    st.subheader("🛠️ Generar Promoción Personalizada")
    with st.expander("ℹ️ Instrucciones"):
        st.write("""
        1. Seleccione un producto
        2. Ajuste el descuento
        3. Defina la fecha límite
        4. Copie el texto generado
        """)
    
    producto_promo = st.selectbox(
        "Producto para promoción",
        options=pedidos['producto'].unique(),
        help="Seleccione el producto a promocionar"
    )
    
    descuento = st.slider(
        "Porcentaje de descuento", 
        min_value=5, 
        max_value=50, 
        value=10,
        help="Descuento a aplicar (5% mínimo para ser atractivo)"
    )
    
    validez = st.date_input(
        "Válido hasta",
        help="Fecha límite para crear sentido de urgencia"
    )
    
    if st.button("Generar texto promocional", help="Clic para generar el mensaje"):
        st.success("**Texto promocional listo para enviar:**")
        st.write(f"""
        "¡Tenemos una oferta especial para usted! 🎉  
        **{descuento}% DE DESCUENTO** en {producto_promo}  
        ⏰ Solo hasta el {validez.strftime('%d/%m/%Y')}  
        📞 Responda a este mensaje con 'SI' para apartar su pedido  
        🚚 Oferta incluye entrega gratuita*  
        
        *Válido para pedidos mayores a RD$2,000. Aplican términos y condiciones."
        """)
        
        st.download_button(
            "Descargar texto",
            data=f"""Oferta especial: {descuento}% en {producto_promo} hasta {validez.strftime('%d/%m/%Y')}""",
            file_name="oferta_promocional.txt"
        )

# ----------------------------------------------------------
# PESTAÑA 5: Alertas y Seguimiento de Clientes
# ----------------------------------------------------------
with tab5:
    st.header("🚨 Alertas y Seguimiento de Clientes")
    
    if not filtered_df.empty:
        # Configuración de umbrales para alertas
        st.subheader("⚙️ Configuración de Alertas")
        col_umbral1, col_umbral2 = st.columns(2)
        
        with col_umbral1:
            dias_alerta_inactivos = st.slider(
                "Días para alerta de clientes inactivos",
                min_value=30,
                max_value=180,
                value=90,
                help="Clientes con más días que este umbral se considerarán para visita urgente"
            )
        
        with col_umbral2:
            umbral_efectividad = st.slider(
                "Umbral mínimo de efectividad (%)",
                min_value=50,
                max_value=95,
                value=80,
                help="Clientes por debajo de este % requieren atención"
            )
        
        # SEMÁFORO DE ALERTAS
        st.subheader("🚦 Semáforo de Alertas por Cliente")
        
        # Calcular alertas
        filtered_df["necesita_visita"] = filtered_df["frecuencia_compra"] > dias_alerta_inactivos
        filtered_df["baja_efectividad"] = filtered_df["efectividad_entrega"] < (umbral_efectividad / 100)
        
        # Contadores de alertas
        total_clientes = len(filtered_df)
        clientes_visita = filtered_df["necesita_visita"].sum()
        clientes_efectividad = filtered_df["baja_efectividad"].sum()
        
        # Mostrar resumen de alertas
        col_alert1, col_alert2, col_alert3 = st.columns(3)
        with col_alert1:
            st.metric("Total Clientes", total_clientes)
        with col_alert2:
            st.metric("Necesitan Visita", clientes_visita, delta=f"{(clientes_visita/total_clientes*100):.1f}%")
        with col_alert3:
            st.metric("Baja Efectividad", clientes_efectividad, delta=f"{(clientes_efectividad/total_clientes*100):.1f}%")
        
        # Tabla de clientes con alertas
        st.subheader("📋 Listado de Clientes con Alertas")
        
        # Crear columna de prioridad
        def calcular_prioridad(fila):
            if fila['necesita_visita'] and fila['baja_efectividad']:
                return "ALTA"
            elif fila['necesita_visita']:
                return "MEDIA"
            elif fila['baja_efectividad']:
                return "BAJA"
            else:
                return "NINGUNA"
        
        filtered_df["prioridad"] = filtered_df.apply(calcular_prioridad, axis=1)
        
        # Filtrar solo clientes con alertas
        clientes_con_alerta = filtered_df[filtered_df["prioridad"] != "NINGUNA"]
        
        if not clientes_con_alerta.empty:
            # Mostrar tabla con alertas
            columnas_alerta = ['nombre', 'codigo_cliente', 'zona', 'frecuencia_compra', 
                             'efectividad_entrega', 'prioridad']
            
            # Aplicar formato condicional
            def estilo_filas(fila):
                if fila['prioridad'] == 'ALTA':
                    return ['background-color: #ffcccc'] * len(fila)
                elif fila['prioridad'] == 'MEDIA':
                    return ['background-color: #fff2cc'] * len(fila)
                elif fila['prioridad'] == 'BAJA':
                    return ['background-color: #e6f3ff'] * len(fila)
                else:
                    return [''] * len(fila)
            
            st.dataframe(
                clientes_con_alerta[columnas_alerta].style.apply(estilo_filas, axis=1),
                use_container_width=True
            )
            
            # Botón para exportar lista de visitas
            if st.button("📥 Exportar Lista de Visitas"):
                visita_data = clientes_con_alerta[['nombre', 'codigo_cliente', 'zona', 'telefono', 'direccion', 'prioridad']]
                csv = visita_data.to_csv(index=False)
                st.download_button(
                    "Descargar CSV",
                    data=csv,
                    file_name=f"visitas_prioritarias_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        else:
            st.success("🎉 No hay clientes con alertas activas según los criterios configurados")
        
        # Gráfico de distribución de alertas
        st.subheader("📊 Distribución de Alertas")
        if not clientes_con_alerta.empty:
            fig_alertas = px.pie(
                clientes_con_alerta,
                names="prioridad",
                title="Distribución de Prioridades de Alerta",
                color="prioridad",
                color_discrete_map={
                    "ALTA": "#ff4444",
                    "MEDIA": "#ffaa00", 
                    "BAJA": "#44aaff"
                }
            )
            st.plotly_chart(fig_alertas, use_container_width=True)
        
    else:
        st.warning("No hay datos para mostrar alertas")

# ----------------------------------------------------------