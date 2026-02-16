import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import sqlite3
import numpy as np
from datetime import datetime

# ============================================
# ЗАГРУЗКА ДАННЫХ ПРИ СТАРТЕ
# ============================================

conn = sqlite3.connect('ev_championship.db')

# Загружаем телематику с одометром
df = pd.read_sql("""
                 SELECT vehicle_id, timestamp, speed_kmh, battery_soc_percent, consumption_kwh_per_100km, driving_style, road_type, avg_temperature_c, odometer
                 FROM telematics_preprocessed
                 WHERE timestamp IS NOT NULL AND odometer IS NOT NULL
                 """, conn)

# Загружаем данные об автомобилях
df_vehicles = pd.read_sql("""
                          SELECT vehicle_id, model, has_problem, battery_health, initial_odometer_km
                          FROM vehicles
                          """, conn)

# Загружаем данные о маршрутах
df_routes = pd.read_sql("""
                        SELECT route_id,
                               vehicle_id,
                               expected_distance_km,
                               planned_start,
                               planned_end,
                               route_type
                        FROM routes
                        WHERE expected_distance_km IS NOT NULL
                        """, conn)
conn.close()

# Подготовка данных
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['date'] = df['timestamp'].dt.date
df['hour'] = df['timestamp'].dt.hour
df['day_of_week'] = df['timestamp'].dt.dayofweek
df['day_name'] = df['timestamp'].dt.day_name()


def get_time_of_day(hour):
    if 6 <= hour < 12:
        return 'Утро'
    elif 12 <= hour < 18:
        return 'День'
    elif 18 <= hour < 22:
        return 'Вечер'
    else:
        return 'Ночь'


df['time_of_day'] = df['hour'].apply(get_time_of_day)



# ============================================
# РАСЧЁТ ДИНАМИКИ ДЕГРАДАЦИИ БАТАРЕЙ
# ============================================

df_vehicles['health_at_entry_pct'] = df_vehicles['battery_health'] * 100
df_vehicles['degradation_to_entry_pct'] = 100.0 - df_vehicles['health_at_entry_pct']
df_vehicles['km_to_entry'] = df_vehicles['initial_odometer_km']
df_vehicles['degradation_rate_per_1000km'] = (
        df_vehicles['degradation_to_entry_pct'] / df_vehicles['km_to_entry'] * 1000
).fillna(0)
df_vehicles['km_to_80'] = (df_vehicles['health_at_entry_pct'] - 80) / df_vehicles['degradation_rate_per_1000km'] * 1000
df_vehicles['years_to_80'] = df_vehicles['km_to_80'] / 15000  # при среднем пробеге 15 тыс. км/год

# ============================================
# DASH APP
# ============================================

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "EV Fleet Dashboard"

vehicle_list = df['vehicle_id'].unique().tolist()
time_list = ['Утро', 'День', 'Вечер', 'Ночь']
road_types = sorted(df['road_type'].dropna().unique().tolist())
driving_styles = sorted(df['driving_style'].dropna().unique().tolist())
min_date = df['date'].min()
max_date = df['date'].max()

app.layout = dbc.Container([
    # АВТООБНОВЛЕНИЕ каждые 2 минуты
    dcc.Interval(id='interval', interval=120000, n_intervals=0),

    html.H3("📊 Аналитика парка ЭТС", className="my-4 text-center"),

    # ФИЛЬТРЫ
    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("Автомобили"),
                    dcc.Dropdown(
                        id='filter-vehicle',
                        options=[{'label': v, 'value': v} for v in vehicle_list],
                        multi=True,
                        value=vehicle_list[:5]
                    )
                ], width=3),
                dbc.Col([
                    html.Label("Период"),
                    dcc.DatePickerRange(
                        id='filter-date',
                        min_date_allowed=min_date,
                        max_date_allowed=max_date,
                        start_date=min_date,
                        end_date=max_date
                    )
                ], width=2),
                dbc.Col([
                    html.Label("Тип дороги"),
                    dcc.Dropdown(
                        id='filter-road',
                        options=[{'label': r, 'value': r} for r in road_types],
                        multi=True,
                        value=road_types
                    )
                ], width=2),
                dbc.Col([
                    html.Label("Стиль вождения"),
                    dcc.Dropdown(
                        id='filter-style',
                        options=[{'label': s, 'value': s} for s in driving_styles],
                        multi=True,
                        value=driving_styles
                    )
                ], width=2),
                dbc.Col([
                    html.Label("Время суток"),
                    dcc.Checklist(
                        id='filter-time',
                        options=[{'label': t, 'value': t} for t in time_list],
                        value=time_list,
                        inline=True
                    )
                ], width=2),
                dbc.Col([
                    html.Label("Статус"),
                    dcc.Dropdown(
                        id='filter-status',
                        options=[{'label': 'Все', 'value': 'all'},
                                 {'label': 'Проблемные', 'value': 'problem'}],
                        value='all'
                    )
                ], width=1),
            ])
        ])
    ], className="mb-4"),

    # KPI
    dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("⚡ Средний расход", className="text-muted"),
            html.H3(id='kpi-cons', children="—"),
            html.Small("кВт⋅ч/100км")
        ])]), width=2),
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🌡️ Температура", className="text-muted"),
            html.H3(id='kpi-temp', children="—"),
            html.Small("°C")
        ])]), width=2),
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🛣️ Тип дороги", className="text-muted"),
            html.H3(id='kpi-road', children="—"),
            html.Small("средний расход")
        ])]), width=2),
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🚗 Скорость", className="text-muted"),
            html.H3(id='kpi-speed', children="—"),
            html.Small("км/ч")
        ])]), width=2),
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🚙 Активные ТС", className="text-muted"),
            html.H3(id='kpi-count', children="—"),
            html.Small("единиц")
        ])]), width=2),
        dbc.Col(dbc.Card([dbc.CardBody([
            html.H6("🔋 Заряд", className="text-muted"),
            html.H3(id='kpi-soc', children="—"),
            html.Small("%")
        ])]), width=2),
    ], className="mb-4"),

    # ГРАФИКИ БЛОК 1
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart1'), width=6),
        dbc.Col(dcc.Graph(id='chart2'), width=6),
    ], className="mb-4"),

    dbc.Row([
        dbc.Col(dcc.Graph(id='chart3'), width=6),
        dbc.Col(dcc.Graph(id='chart4'), width=6),
    ], className="mb-4"),

    # ГРАФИКИ БЛОК 2: АНАЛИТИКА ПО ТРЕБОВАНИЯМ Б.2
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart5'), width=6),
        dbc.Col(dcc.Graph(id='chart6'), width=6),
    ], className="mb-4"),

    # ГРАФИК 7: Средний расход по времени суток
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart7'), width=12),
    ], className="mb-4"),

    # ГРАФИК 8: Распределение активности по автомобилям
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart8'), width=12),
    ], className="mb-4"),

    # ГРАФИК 9: ДИНАМИКА ДЕГРАДАЦИИ БАТАРЕЙ
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart9'), width=12),
    ], className="mb-4"),

    # ГРАФИК 10: ЭФФЕКТИВНОСТЬ МАРШРУТОВ
    dbc.Row([
        dbc.Col(dcc.Graph(id='chart10'), width=12),
    ], className="mb-4"),

    html.Hr(),
    html.P(id='last-update', className="text-center text-muted")

], fluid=True)


# ============================================
# CALLBACK
# ============================================

@app.callback(
    [Output('kpi-cons', 'children'),
     Output('kpi-temp', 'children'),
     Output('kpi-road', 'children'),
     Output('kpi-speed', 'children'),
     Output('kpi-count', 'children'),
     Output('kpi-soc', 'children'),
     Output('chart1', 'figure'),
     Output('chart2', 'figure'),
     Output('chart3', 'figure'),
     Output('chart4', 'figure'),
     Output('chart5', 'figure'),
     Output('chart6', 'figure'),
     Output('chart7', 'figure'),
     Output('chart8', 'figure'),
     Output('chart9', 'figure'),
     Output('chart10', 'figure'),
     Output('last-update', 'children')],
    [Input('interval', 'n_intervals'),
     Input('filter-vehicle', 'value'),
     Input('filter-date', 'start_date'),
     Input('filter-date', 'end_date'),
     Input('filter-road', 'value'),
     Input('filter-style', 'value'),
     Input('filter-time', 'value'),
     Input('filter-status', 'value')]
)
def update(n, vehicles, start_date, end_date, roads, styles, times, status):
    try:
        # Перезагрузка данных из БД
        conn = sqlite3.connect('ev_championship.db')
        df_new = pd.read_sql("""
                             SELECT vehicle_id, timestamp, speed_kmh, battery_soc_percent, consumption_kwh_per_100km, driving_style, road_type, avg_temperature_c, odometer
                             FROM telematics_preprocessed
                             WHERE timestamp IS NOT NULL AND odometer IS NOT NULL
                             """, conn)

        # Загрузка данных о батареях
        vehicles_data = pd.read_sql("""
                                    SELECT vehicle_id, model, has_problem, battery_health, initial_odometer_km
                                    FROM vehicles
                                    """, conn)

        # Расчёт динамики деградации
        vehicles_data['health_at_entry_pct'] = vehicles_data['battery_health'] * 100
        vehicles_data['degradation_to_entry_pct'] = 100.0 - vehicles_data['health_at_entry_pct']
        vehicles_data['km_to_entry'] = vehicles_data['initial_odometer_km']
        vehicles_data['degradation_rate_per_1000km'] = (
                vehicles_data['degradation_to_entry_pct'] / vehicles_data['km_to_entry'] * 1000
        ).fillna(0)
        vehicles_data['km_to_80'] = (vehicles_data['health_at_entry_pct'] - 80) / vehicles_data[
            'degradation_rate_per_1000km'] * 1000
        vehicles_data['years_to_80'] = vehicles_data['km_to_80'] / 15000

        # Загрузка данных о маршрутах
        routes_plan = pd.read_sql("""
                                  SELECT route_id,
                                         vehicle_id,
                                         expected_distance_km,
                                         planned_start,
                                         planned_end,
                                         route_type
                                  FROM routes
                                  WHERE expected_distance_km IS NOT NULL
                                  """, conn)
        conn.close()

        # Подготовка данных
        df_new['timestamp'] = pd.to_datetime(df_new['timestamp'])
        df_new['date'] = df_new['timestamp'].dt.date
        df_new['hour'] = df_new['timestamp'].dt.hour
        df_new['day_of_week'] = df_new['timestamp'].dt.dayofweek
        df_new['day_name'] = df_new['timestamp'].dt.day_name()
        df_new['time_of_day'] = df_new['hour'].apply(get_time_of_day)

        dff = df_new.copy()

        # Фильтрация
        if vehicles:
            dff = dff[dff['vehicle_id'].isin(vehicles)]
        if start_date and end_date:
            start = pd.to_datetime(start_date).date()
            end = pd.to_datetime(end_date).date()
            dff = dff[(dff['date'] >= start) & (dff['date'] <= end)]
        if roads:
            dff = dff[dff['road_type'].isin(roads)]
        if styles:
            dff = dff[dff['driving_style'].isin(styles)]
        if times:
            dff = dff[dff['time_of_day'].isin(times)]
        if status == 'problem':
            problem_ids = vehicles_data[vehicles_data['has_problem'] == 1]['vehicle_id'].tolist()
            dff = dff[dff['vehicle_id'].isin(problem_ids)]

        # Проверка данных
        if len(dff) == 0:
            empty = px.scatter(title="Нет данных после фильтрации")
            update_time = f"Обновлено: {datetime.now().strftime('%H:%M:%S')} | Нет данных"
            return ["Н/Д"] * 6 + [empty] * 10 + [update_time]

        # KPI
        kpi_cons = f"{dff['consumption_kwh_per_100km'].mean():.1f}"
        kpi_temp = f"{dff['avg_temperature_c'].mean():.1f}"
        road_avg = dff.groupby('road_type')['consumption_kwh_per_100km'].mean()
        kpi_road = road_avg.idxmin() if not road_avg.empty else "—"
        kpi_speed = f"{dff['speed_kmh'].mean():.1f}"
        kpi_count = str(dff['vehicle_id'].nunique())
        kpi_soc = f"{dff['battery_soc_percent'].mean():.1f}"

        # График 1: Тренд по дням недели
        dow_data = dff.groupby('day_of_week')['consumption_kwh_per_100km'].mean().reset_index()
        dow_data['day_name'] = dow_data['day_of_week'].map(
            {0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс'})
        fig1 = px.line(dow_data, x='day_name', y='consumption_kwh_per_100km',
                       title='📈 Средний расход по дням недели', markers=True, template='plotly_white')
        fig1.update_traces(line_color='#2ecc71', line_width=3)
        fig1.update_layout(xaxis_title="День недели", yaxis_title="Расход (кВт⋅ч/100км)")

        # График 2: Зависимость от температуры
        temp_data = dff[['avg_temperature_c', 'consumption_kwh_per_100km']].dropna()
        if len(temp_data) > 20:
            sample_size = min(2000, len(temp_data))
            temp_sample = temp_data.sample(n=sample_size) if len(temp_data) > sample_size else temp_data
            fig2 = px.scatter(temp_sample, x='avg_temperature_c', y='consumption_kwh_per_100km',
                              title='🌡️ Расход от температуры', opacity=0.6, template='plotly_white')
            fig2.update_layout(xaxis_title="Температура (°C)", yaxis_title="Расход (кВт⋅ч/100км)")
        else:
            fig2 = px.scatter(title="Недостаточно данных для анализа температуры")

        # График 3: Тип дороги + стиль вождения
        road_style = dff.groupby(['road_type', 'driving_style'])['consumption_kwh_per_100km'].mean().reset_index()
        if not road_style.empty:
            fig3 = px.bar(road_style.sort_values('consumption_kwh_per_100km'),
                          x='road_type', y='consumption_kwh_per_100km', color='driving_style',
                          title='🛣️ Влияние дороги и стиля на расход', barmode='group', template='plotly_white')
            fig3.update_layout(xaxis_title="Тип дороги", yaxis_title="Средний расход")
        else:
            fig3 = px.scatter(title="Нет данных для анализа дорог")

        # График 4: Скорость vs Расход
        speed_data = dff[['speed_kmh', 'consumption_kwh_per_100km']].dropna()
        # Убираем нулевой расход и экстремальные выбросы
        speed_clean = speed_data[
            (speed_data['consumption_kwh_per_100km'] > 0.5) &  # Минимальный реальный расход
            (speed_data['consumption_kwh_per_100km'] < 80) &  # Максимум 80 кВтч/100км
            (speed_data['speed_kmh'] > 5)  # Движение, не стоянка
            ]
        if len(speed_clean) > 20:
            sample_size = min(2000, len(speed_clean))
            speed_sample = speed_clean.sample(n=sample_size) if len(speed_clean) > sample_size else speed_clean
            fig4 = px.scatter(speed_sample, x='speed_kmh', y='consumption_kwh_per_100km',
                      title='⚡ Скорость vs Расход',
                      opacity=0.6, template='plotly_white')
            fig4.update_layout(xaxis_title="Скорость (км/ч)", yaxis_title="Расход (кВт⋅ч/100км)")
        else:
            fig4 = px.scatter(title="Нет данных для анализа скорости")

        # График 5: Тепловая карта время суток × день недели
        heatmap_data = dff.groupby(['day_of_week', 'time_of_day'])['consumption_kwh_per_100km'].mean().reset_index()
        if not heatmap_data.empty:
            heatmap_data['day_name'] = heatmap_data['day_of_week'].map(
                {0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс'}
            )
            fig5 = px.density_heatmap(heatmap_data, x='time_of_day', y='day_name',
                                      z='consumption_kwh_per_100km',
                                      title='📊 Тепловая карта: время × день',
                                      color_continuous_scale='RdYlGn_r', template='plotly_white')
            fig5.update_layout(xaxis_title="Время суток", yaxis_title="День недели")
        else:
            fig5 = px.scatter(title="Нет данных для тепловой карты")

        # График 6: Рейтинг эффективности
        vehicle_stats = dff.groupby('vehicle_id')['consumption_kwh_per_100km'].mean().reset_index()
        if not vehicle_stats.empty:
            vehicle_stats = vehicle_stats.sort_values('consumption_kwh_per_100km').head(15)
            fig6 = px.bar(vehicle_stats, x='vehicle_id', y='consumption_kwh_per_100km',
                          title='🏆 Топ-15 самых эффективных автомобилей',
                          template='plotly_white', color='consumption_kwh_per_100km',
                          color_continuous_scale='RdYlGn_r')
            fig6.update_layout(xaxis_title="Автомобиль", yaxis_title="Средний расход (кВт⋅ч/100км)")
        else:
            fig6 = px.scatter(title="Нет данных для рейтинга")

        # График 7: Средний расход по времени суток
        time_data = dff.groupby('time_of_day')['consumption_kwh_per_100km'].mean().reset_index()
        time_order = ['Утро', 'День', 'Вечер', 'Ночь']
        time_data['sort_key'] = time_data['time_of_day'].map({t: i for i, t in enumerate(time_order)})
        time_data = time_data.sort_values('sort_key')
        fig7 = px.bar(time_data, x='time_of_day', y='consumption_kwh_per_100km',
                      title='⏰ Средний расход энергии по времени суток',
                      template='plotly_white', color='consumption_kwh_per_100km',
                      color_continuous_scale='RdYlGn_r')
        fig7.update_layout(xaxis_title="Время суток", yaxis_title="Расход (кВт⋅ч/100км)")

        # График 8: Распределение активности по автомобилям
        activity_data = dff.groupby('vehicle_id').size().reset_index(name='activity_count')
        activity_data = activity_data.sort_values('activity_count', ascending=False).head(20)
        fig8 = px.bar(activity_data, x='vehicle_id', y='activity_count',
                      title='📊 Распределение активности по автомобилям (топ-20)',
                      template='plotly_white', color='activity_count',
                      color_continuous_scale='Blues')
        fig8.update_layout(xaxis_title="Автомобиль", yaxis_title="Количество записей (активность)")

        # ============================================
        # ГРАФИК 9: ДИНАМИКА ДЕГРАДАЦИИ БАТАРЕЙ
        # ============================================
        fig9 = px.scatter(
            vehicles_data,
            x='health_at_entry_pct',
            y='degradation_rate_per_1000km',
            color='has_problem',
            color_discrete_map={True: 'red', False: 'green'},
            size='degradation_rate_per_1000km',
            title='🔋 Динамика деградации батарей: текущее состояние и скорость падения ёмкости',
            template='plotly_white',
            labels={
                'health_at_entry_pct': 'Текущее состояние батареи (%)',
                'degradation_rate_per_1000km': 'Скорость деградации (% на 1000 км)',
                'has_problem': 'Проблемы'
            },
            hover_data={
                'model': True,
                'km_to_entry': True,
                'years_to_80': True
            }
        )
        fig9.update_layout(
            xaxis_range=[70, 100],
            yaxis_range=[0, max(vehicles_data['degradation_rate_per_1000km'].max() * 1.2, 1.0)],
            xaxis_title="Текущее состояние батареи (%)",
            yaxis_title="Скорость деградации (% на 1000 км)",
            showlegend=True,
            legend_title="Проблемы"
        )
        fig9.add_hline(y=0.25, line_dash="dash", line_color="orange",
                       annotation_text="Норма ≤0.25%", annotation_position="top right")
        fig9.add_vline(x=80, line_dash="dash", line_color="orange",
                       annotation_text="Порог 80%", annotation_position="top right")

        # ============================================
        # ГРАФИК 10: ЭФФЕКТИВНОСТЬ МАРШРУТОВ (ЗАГЛУШКА)
        # ============================================
        fig10 = go.Figure()
        fig10.update_layout(
            title="🛣️ Эффективность маршрутов: анализ план/факт времени",
            template='plotly_white',
            height=400
        )

        update_time = f"Обновлено: {datetime.now().strftime('%H:%M:%S')} | Записей: {len(df_new):,}"

        return [kpi_cons, kpi_temp, kpi_road, kpi_speed, kpi_count, kpi_soc,
                fig1, fig2, fig3, fig4, fig5, fig6, fig7, fig8, fig9, fig10,
                update_time]

    except Exception as e:
        empty = px.scatter(title=f"Ошибка: {str(e)[:50]}")
        update_time = f"Ошибка: {datetime.now().strftime('%H:%M:%S')}"
        return ["Ошибка"] * 6 + [empty] * 9 + [go.Figure()] + [update_time]


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8050)