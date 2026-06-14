from .models import db, WasteCategory, StorageLocation


def init_db():
    db.create_all()
    _seed_sample_data()


def _seed_sample_data():
    if WasteCategory.query.count() == 0:
        categories = [
            WasteCategory(
                code='HW08',
                name='废矿物油',
                description='废矿物油与含矿物油废物'
            ),
            WasteCategory(
                code='HW12',
                name='染料涂料废物',
                description='染料、涂料废物'
            )
        ]
        db.session.add_all(categories)
        db.session.flush()
        print(f"已创建 {len(categories)} 个危废类别")
    else:
        categories = WasteCategory.query.all()

    if StorageLocation.query.count() == 0:
        cat1 = WasteCategory.query.filter_by(code='HW08').first()
        cat2 = WasteCategory.query.filter_by(code='HW12').first()

        locations = [
            StorageLocation(
                code='STORE-A',
                name='A库区-矿物油暂存区',
                max_capacity_kg=5000.0,
                allowed_category_ids=str(cat1.id)
            ),
            StorageLocation(
                code='STORE-B',
                name='B库区-涂料废物暂存区',
                max_capacity_kg=3000.0,
                allowed_category_ids=str(cat2.id)
            )
        ]
        db.session.add_all(locations)
        print(f"已创建 {len(locations)} 个库位")

    db.session.commit()
