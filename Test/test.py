import pandas as pd
import plotly.express as px

# ================= 1. 数据清洗部分 =================
print("正在读取并清洗数据...")
df = pd.read_csv("data.csv")

# 删除带有缺失值的关键行
df = df.dropna(subset=['平方', '价格', '平方价格'])

# 将文本格式的数据提取为纯数字，方便画图
df['面积(㎡)'] = df['平方'].astype(str).str.replace(' 平米', '', regex=False).astype(float)
df['总价(万)'] = df['价格'].astype(str).str.replace('万', '', regex=False).astype(float)
df['单价(元/㎡)'] = df['平方价格'].astype(str).str.replace('元/m²', '', regex=False).astype(float)

# 提取核心位置板块 (例如从 "老余杭 圆乡名筑" 提取出 "老余杭")
df['板块'] = df['位置'].astype(str).apply(lambda x: x.split(' ')[0])

print("数据清洗完毕！总有效数据量：", len(df), "条")

# ================= 2. 可视化绘图部分 =================

# 【图表1】杭州热门板块二手房均价与房源量气泡图
# 统计各个板块的数据
board_stats = df.groupby('板块').agg({
    '总价(万)': 'mean',
    '单价(元/㎡)': 'mean',
    '甄选': 'count',
    '关注量': 'sum'
}).reset_index()
board_stats.rename(columns={'甄选': '房源数量', '单价(元/㎡)': '平均单价'}, inplace=True)
top_20_boards = board_stats.nlargest(20, '房源数量') # 取房源量前20的热门板块

fig1 = px.scatter(top_20_boards, x='房源数量', y='平均单价',
                  size='关注量', color='板块', text='板块',
                  title='杭州Top20热门板块二手房：均价 vs 供应量 vs 关注热度(气泡大小)',
                  labels={'房源数量': '二手房挂牌数量(套)', '平均单价': '平均单价(元/平米)'})
fig1.update_traces(textposition='top center')
fig1.show()

# 【图表2】杭州主流户型总价分布箱线图
# 筛选出市面上数量最多的 5 种户型
top_5_layouts = df['户型'].value_counts().nlargest(5).index
df_top_layout = df[df['户型'].isin(top_5_layouts)]

fig2 = px.box(df_top_layout, x='户型', y='总价(万)', color='户型',
              title='杭州Top 5主流二手房户型总价分布特征（寻找价格异常值）',
              labels={'总价(万)': '房屋总价(万元)'})
fig2.show()

# 【图表3】面积与总价的线性关系散点图
# 为了图表美观，我们随机抽取 2000 条数据进行绘制防重叠
df_sample = df_top_layout.sample(2000, random_state=42)
fig3 = px.scatter(df_sample, x='面积(㎡)', y='总价(万)', color='户型',
                  title='杭州二手房面积与总价关系图 (同面积下寻找高性价比户型)',
                  trendline="ols") # 添加回归趋势线
fig3.show()