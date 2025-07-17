## Tìm hiểu về CRM:

Tóm tắt khái niệm: https://youtu.be/SYsBp7kOWdk?si=Gbu1faGGwrq2Y-Z-
Về module CRM của Odoo: https://youtu.be/E2zkTZuW2Vc?si=zXzqEv36BMp87xFR

## Nguồn học tập:
Core: https://youtube.com/playlist?list=PLqRRLx0cl0hoZM788LH5M8q7KhiXPyuVU&si=-NVKnab_4Dy-Hsss
Odoo 17: https://youtube.com/playlist?list=PLqRRLx0cl0hq0T4SV-BHhCicWOpzyWcHd&si=h6a9DMXcxaILI9Yo
Frontend - Odoo view: https://youtube.com/playlist?list=PLAR8TpPnVeTTwiF0XXA92_h1__kmvAmQp&si=QahTwF4eak9WtU5U

## Tài liệu:
https://www.odoo.com/documentation/17.0/

## Tải các tài nguyên:
Python 3.12.10: https://www.python.org/downloads/release/python-31210/
PostgreSql 15.13: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
Odoo 17.0: https://github.com/odoo/odoo/tree/17.0 (không được clone, phải chọn bản 17.0 trên nhánh và tải xuống file zip)

## Config:
**Video hướng dẫn config**
Recommend: https://youtu.be/jJXZcqiJG4Y?si=F9SXGUHYxyGKJVIc
Cách config khác (yêu cầu phải tải các package về truớc): https://youtu.be/p7SJW36lqVE?si=3i79TTFpMwwu2DxP


**Tạo file odoo.conf:**
```
//Tên host và cổng port cho server trên PostgreSQL
[options]
db_host = localhost
db_port = 5432

//Tên group_roles cùng với pass đã tạo trên PostGre (lưu ý phải tạo trên PostGre trước và cấp toàn quyền
db_user = odoo
db_password = 12345

//Tên db
db_name = odoo_learning

//Truyền path của thư mục addons trong project (mặc định sẽ là addons, nếu báo lỗi thì truyền đúng đường dẫn)
addons_path = addons
```

**Terminal config (sử dụng terminal):**
```
python -m venv virtual //chạy đầu tiên
virtual\Scripts\activate (deactivate hoặc ghi "exit" để dừng toàn bộ chương trình)
python odoo-bin -c odoo.conf -d <tên_db> -i base //Lưu ý: database phải là một database rỗng tức chưa có Schema
pip install setuptools wheel
pip install -r requirements.txt
```
**Lệnh chạy chương trình với file odoo.conf**
`python odoo-bin -c odoo.conf`