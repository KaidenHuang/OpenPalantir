# 数据库Schema业务标注任务

## 任务描述

你是一个数据库专家，拥有丰富的数据库库表设计经验以及上层业务逻辑经验，请分析以下数据库Schema，完成业务标注任务：

1. 为每个表添加业务描述和实体类型
2. 为每个字段添加业务描述
3. 根据外键约束推断表间业务关联关系
4. 为整个数据库生成概要描述

***

## 输入数据

### 数据库表结构

{tables_info}

### 字段详情

{columns_text}

### 外键关联

{fk_text}

***

## 标注要求

### 表标注字段说明

| 缩写 | 原字段 | 必填 | 说明 |
| ---- | ------ | ---- | ---- |
| t    | table_name | 是 | 表名 |
| d    | business_description | 是 | 表的业务描述 |
| et   | entity_type | 是 | 实体类型 |

### 字段标注字段说明

| 缩写 | 原字段 | 必填 | 说明 |
| ---- | ------ | ---- | ---- |
| c    | column_name | 是 | 字段名 |
| d    | business_description | 是 | 字段的业务描述 |

### 数据库概要字段说明

| 缩写 | 原字段 | 必填 | 说明 |
| ---- | ------ | ---- | ---- |
| ov   | overview | 是 | 数据库整体概要描述 |
| dom  | business_domain | 是 | 业务领域分类 |
| ke   | key_entities | 是 | 关键业务实体说明 |

### 关系推断字段说明

| 缩写 | 原字段 | 必填 | 说明 |
| ---- | ------ | ---- | ---- |
| s    | source_table | 是 | 源表名 |
| sc   | source_column | 是 | 源字段名 |
| t    | target_table | 是 | 目标表名 |
| tc   | target_column | 是 | 目标字段名 |
| r    | relationship_type | 是 | 关系类型 |
| d    | description | 否 | 关系描述 |

### 可选值列表

**实体类型选项（返回时使用英文）：**

- person：人物相关表，如员工、客户、联系人等
- organization：组织相关表，如公司、部门、团队等
- location：地点相关表，如地址、区域、场所等
- event：事件相关表，如会议、活动、订单等
- concept：概念相关表，如产品、类别、标签等
- other：无法归类的其他表

**关系类型选项：**

- 包含：一对多关系，如订单包含订单项
- 属于：多对一关系，如订单属于用户
- 引用：外键引用关系
- 关联：一般关联关系
- 依赖：依赖关系
- 其他：无法归类的关系

***

## 输出格式

请严格按照以下JSON格式返回结果。字段使用缩写（见上方说明）。

```json
{
  "db": {
    "ov": "数据库整体概要描述",
    "dom": "业务领域分类",
    "ke": "关键业务实体说明"
  },
  "tables": [
    {
      "t": "表名",
      "d": "业务描述",
      "et": "实体类型",
      "cols": [
        { "c": "字段名", "d": "字段描述" }
      ]
    }
  ],
  "rels": [
    {
      "s": "源表", "sc": "源字段",
      "t": "目标表", "tc": "目标字段",
      "r": "关系类型", "d": "关系描述"
    }
  ]
}
```

***

## 格式要求（请严格遵守）

### 必须满足的条件

1. **只返回JSON格式**：不要添加任何额外的文本，如解释、说明、思考过程等
2. **字段完整性**：每个表必须包含t、d、et字段
3. **字段完整性**：每个表内的cols数组必须包含每个字段的c、d字段
4. **database_summary完整性**：db对象必须包含ov、dom、ke字段
5. **字段类型正确**：所有字段都是string类型
6. **使用缩写**：必须使用上方表格中指定的缩写字段名（t/d/et/c/ov/dom/ke/s/sc/tc/r）

### JSON格式检查清单

在返回结果之前，请仔细检查以下内容：

- [ ] 只返回纯JSON，无任何前缀或后缀文本
- [ ] 所有属性名使用双引号包裹
- [ ] 所有字符串值使用双引号包裹
- [ ] 数组和对象最后一个元素后没有多余逗号
- [ ] 所有括号正确配对（{}和[]）
- [ ] JSON可以被标准JSON解析器正确解析

### 约束条件

1. **覆盖完整性**：尽可能为所有表和字段提供标注
2. **避免冗余**：使用简洁的描述
3. **一致性**：相同类型的表/字段使用一致的命名和描述
4. **如果无法确定，使用"其他"**

***

## 示例参考

### 输入示例

```
## 数据库表结构
- users: TABLE
- orders: TABLE
- order_items: TABLE

## 字段详情
- users: [id(int), name(varchar), email(varchar), created_at(datetime)]
- orders: [id(int), user_id(int), total_amount(decimal), status(varchar), created_at(datetime)]
- order_items: [id(int), order_id(int), product_name(varchar), quantity(int), price(decimal)]

## 外键关联
- orders.user_id -> users.id
- order_items.order_id -> orders.id
```

### 输出示例

```json
{
  "db": {
    "ov": "电商业务数据库，存储用户、订单和订单项信息",
    "dom": "电商",
    "ke": "users为核心用户实体，orders为订单交易实体，order_items为订单行项目实体"
  },
  "tables": [
    {
      "t": "users",
      "d": "存储用户信息",
      "et": "person",
      "cols": [
        { "c": "id", "d": "用户唯一标识" },
        { "c": "name", "d": "用户姓名" },
        { "c": "email", "d": "用户邮箱" },
        { "c": "created_at", "d": "注册时间" }
      ]
    },
    {
      "t": "orders",
      "d": "存储订单信息",
      "et": "event",
      "cols": [
        { "c": "id", "d": "订单唯一标识" },
        { "c": "user_id", "d": "下单用户ID" },
        { "c": "total_amount", "d": "订单总金额" },
        { "c": "status", "d": "订单状态" },
        { "c": "created_at", "d": "下单时间" }
      ]
    },
    {
      "t": "order_items",
      "d": "存储订单项信息",
      "et": "event",
      "cols": [
        { "c": "id", "d": "订单项唯一标识" },
        { "c": "order_id", "d": "所属订单ID" },
        { "c": "product_name", "d": "商品名称" },
        { "c": "quantity", "d": "购买数量" },
        { "c": "price", "d": "商品单价" }
      ]
    }
  ],
  "rels": [
    { "s": "orders", "sc": "user_id", "t": "users", "tc": "id", "r": "属于", "d": "订单属于用户" },
    { "s": "order_items", "sc": "order_id", "t": "orders", "tc": "id", "r": "包含", "d": "订单包含订单项" }
  ]
}
```
