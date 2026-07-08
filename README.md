# Meta Ads — Creative Performance Reporter

Static dashboard báo cáo hiệu quả **creative (ad-level)** của các ad account Chotot.
Data lấy từ Meta Marketing API → render ra HTML tĩnh → host trên GitHub Pages,
tự refresh mỗi tuần bằng GitHub Actions.

```
Meta Graph API ──> build_report.py ──> docs/data/latest.json ──> docs/index.html
                        ▲                                              │
              GitHub Actions (cron)                            GitHub Pages serve
```

## Cấu trúc

| File | Vai trò |
|---|---|
| `build_report.py` | Pull ad-level insights cho mỗi account, ghi `docs/data/latest.json` |
| `docs/index.html` | Dashboard, đọc `data/latest.json` và render bảng creative |
| `docs/data/latest.json` | Data mới nhất (đã seed sẵn số thật để chạy offline) |
| `.github/workflows/weekly.yml` | Chạy `build_report.py` mỗi thứ 2 09:00 ICT, commit data mới |
| `requirements.txt` | Thư viện Python (`requests`) |

## Chạy thử ở máy (local)

```bash
# 1. Xem dashboard với data seed sẵn
cd docs && python3 -m http.server 8000
#    -> mở http://localhost:8000

# 2. Pull data mới từ Meta (cần token)
pip install -r requirements.txt
export META_ACCESS_TOKEN="EAAB..."   # token có quyền ads_read + read_insights
python build_report.py               # ghi đè docs/data/latest.json
```

> Không set `META_ACCESS_TOKEN` thì script giữ nguyên data seed — dashboard vẫn chạy.

## Deploy lên GitHub Pages

1. Tạo repo mới trên GitHub, push toàn bộ folder này lên nhánh `main`.
2. **Settings → Pages** → Source: `Deploy from a branch` → Branch `main` / folder `/docs` → Save.
   Sau ~1 phút dashboard sống ở `https://<user>.github.io/<repo>/`.
3. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `META_ACCESS_TOKEN`
   - Value: Meta access token (System User token cho bền, scope `ads_read` + `read_insights`).
4. **Settings → Actions → General → Workflow permissions** → chọn `Read and write permissions`
   (để Action commit được data mới).
5. Xong. Mỗi thứ 2 workflow tự pull data và cập nhật dashboard.
   Muốn chạy ngay: tab **Actions → Weekly Creative Performance → Run workflow**.

## Chỉnh account / chỉ số

- Thêm/bớt account: sửa dict `ACCOUNTS` trong `build_report.py`.
- Đổi khoảng thời gian: sửa `DATE_PRESET` (vd `last_7d`, `last_14d`).
- Thêm chỉ số: thêm field vào `FIELDS` + map trong `fetch_creatives()`, rồi thêm cột trong `COLS` ở `docs/index.html`.

> Lưu ý: account `Chotot_veh_sgd` hiện chưa bật Ads MCP nhưng token Marketing API chuẩn vẫn pull được.
