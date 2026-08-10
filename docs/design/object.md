# EMIP_OBJECT 設計

## 資料表用途

`EMIP_OBJECT` 是 EMIP 的 Metadata Object 主資料表，用於儲存由原始碼、資料庫、ETL、檔案、API、FTP 與未來整合來源發現的 Metadata Object。

資料表名稱遵循 EMIP 資料表命名規範，固定使用 `EMIP_` 前綴。本次只建立 `EMIP_OBJECT`，不包含版本、關聯、欄位或屬性資料表。

## 欄位說明

| 欄位 | 型別 | 可為 NULL | 說明 |
|---|---|---:|---|
| `OBJECT_ID` | `UUID` | 否 | Metadata Object 唯一識別碼。 |
| `OBJECT_TYPE` | `VARCHAR(50)` | 否 | Object 類型，例如 `TABLE`、`VIEW` 或 `FILE`。 |
| `SYSTEM_NAME` | `VARCHAR(50)` | 否 | 來源系統名稱。 |
| `QUALIFIED_NAME` | `VARCHAR(1000)` | 否 | 來源系統中的完整限定名稱。 |
| `NAME` | `VARCHAR(255)` | 否 | Object 名稱。 |
| `DISPLAY_NAME` | `VARCHAR(255)` | 否 | 顯示用名稱。 |
| `DESCRIPTION` | `TEXT` | 是 | Object 說明。 |
| `OWNER_NAME` | `VARCHAR(255)` | 是 | Object 擁有者或負責人。 |
| `STATUS` | `VARCHAR(30)` | 否 | Object 生命週期狀態。 |
| `CREATED_AT` | `TIMESTAMP` | 否 | Metadata Object 建立時間。 |
| `UPDATED_AT` | `TIMESTAMP` | 否 | Metadata Object 最近更新時間。 |

## Constraints

- `EMIP_PK_OBJECT`：以 `OBJECT_ID` 建立 Primary Key。
- `EMIP_UK_OBJECT`：以 `SYSTEM_NAME` 與 `QUALIFIED_NAME` 建立 Unique Constraint，確保同一來源系統內的限定名稱唯一。

## Indexes

- `EMIP_IDX_OBJECT_NAME`：建立於 `NAME`，支援依 Object 名稱查詢。
- `EMIP_IDX_OBJECT_TYPE`：建立於 `OBJECT_TYPE`，支援依 Object 類型篩選。

## Greenplum 分布策略

資料表使用 `DISTRIBUTED REPLICATED`。本資料表同時要求 `OBJECT_ID` Primary Key 與 `(SYSTEM_NAME, QUALIFIED_NAME)` Unique Constraint；複製分布可在不增加欄位且不改變指定鍵的前提下保留兩項約束。

Migration 檔案：`scripts/sql/001_create_emip_object.sql`。