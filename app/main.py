from collections import defaultdict
from datetime import date, datetime
import uuid

import pandas as pd
import streamlit as st
from sqlalchemy import text

from scraper_service import scrape_url
from db import Base, engine, SessionLocal
from models import OwnedPerfume, WatchedPerfume, WatchedUrl, PriceHistory
from concurrent.futures import ThreadPoolExecutor, as_completed

Base.metadata.create_all(bind=engine)


def run_schema_migrations():
    with engine.begin() as conn:
        columns = conn.execute(text("PRAGMA table_info(price_history)")).fetchall()
        column_names = {col[1] for col in columns}

        if columns and "check_run_id" not in column_names:
            conn.execute(text("ALTER TABLE price_history ADD COLUMN check_run_id VARCHAR(64)"))


run_schema_migrations()

st.set_page_config(page_title="Parfumareala", layout="wide")
st.title("Parfumareala")


def get_owned_perfumes():
    db = SessionLocal()
    items = db.query(OwnedPerfume).order_by(
        OwnedPerfume.brand.asc(),
        OwnedPerfume.name.asc(),
        OwnedPerfume.volume_ml.asc()
    ).all()
    db.close()
    return items


def get_watched_perfumes():
    db = SessionLocal()
    items = db.query(WatchedPerfume).order_by(
        WatchedPerfume.brand.asc(),
        WatchedPerfume.name.asc(),
        WatchedPerfume.volume_ml.asc()
    ).all()
    db.close()
    return items


def get_watched_urls():
    db = SessionLocal()
    items = db.query(WatchedUrl).order_by(WatchedUrl.id.desc()).all()
    db.close()
    return items


def format_price_change(current_price, previous_price):
    if current_price is None:
        return "Fără preț"

    if previous_price is None:
        return "Prima valoare"

    delta = round(current_price - previous_price, 2)

    if delta == 0:
        return "Neschimbat"

    if delta > 0:
        return f"Crescut cu {delta} lei"

    return f"Scăzut cu {abs(delta)} lei"


def build_history_records():
    db = SessionLocal()

    history_items = db.query(PriceHistory).order_by(
        PriceHistory.checked_at.asc(),
        PriceHistory.id.asc()
    ).all()

    watched_urls = {item.id: item for item in db.query(WatchedUrl).all()}
    watched_perfumes = {item.id: item for item in db.query(WatchedPerfume).all()}

    last_price_by_url_id = {}
    records = []

    for item in history_items:
        watched_url = watched_urls.get(item.watched_url_id)
        perfume = watched_perfumes.get(watched_url.watched_perfume_id) if watched_url else None

        perfume_id = perfume.id if perfume else None
        perfume_label = f"{perfume.brand} - {perfume.name}" if perfume else "Necunoscut"
        target_volume = perfume.volume_ml if perfume else None
        shop_name = watched_url.shop_name if watched_url else None

        previous_price = last_price_by_url_id.get(item.watched_url_id)
        change_label = format_price_change(item.price, previous_price)

        if item.price is not None:
            last_price_by_url_id[item.watched_url_id] = item.price

        run_id = item.check_run_id or (
            item.checked_at.strftime("%Y-%m-%d %H:%M:%S") if item.checked_at else f"legacy-{item.id}"
        )

        records.append(
            {
                "run_id": run_id,
                "checked_at_dt": item.checked_at,
                "checked_at_display": item.checked_at.strftime("%Y-%m-%d %H:%M:%S") if item.checked_at else None,
                "perfume_id": perfume_id,
                "perfume_label": perfume_label,
                "target_volume_ml": target_volume,
                "shop_name": shop_name,
                "price": item.price,
                "currency": item.currency,
                "in_stock": item.in_stock,
                "extracted_title": item.extracted_title,
                "error_message": item.error_message,
                "price_change": change_label,
            }
        )

    db.close()
    return records

def scrape_single_url(url_obj):
    db = SessionLocal()
    perfume = db.query(WatchedPerfume).filter(
        WatchedPerfume.id == url_obj.watched_perfume_id
    ).first()
    db.close()

    perfume_label = f"{perfume.brand} - {perfume.name}" if perfume else "Necunoscut"
    target_volume = perfume.volume_ml if perfume else None

    try:
        result = scrape_url(
            url_obj.product_url,
            expected_volume_ml=target_volume,
        )

        return {
            "ok": True,
            "watched_url_id": url_obj.id,
            "checked_at": datetime.now(),
            "Parfum": perfume_label,
            "Magazin": url_obj.shop_name,
            "Volum țintă": target_volume,
            "Titlu extras": result.title,
            "Volum extras": result.volume_ml,
            "Preț": result.price,
            "Monedă": result.currency,
            "În stoc": result.in_stock,
            "Eroare": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "watched_url_id": url_obj.id,
            "checked_at": datetime.now(),
            "Parfum": perfume_label,
            "Magazin": url_obj.shop_name,
            "Volum țintă": target_volume,
            "Titlu extras": None,
            "Volum extras": None,
            "Preț": None,
            "Monedă": None,
            "În stoc": None,
            "Eroare": str(e),
        }

def run_scrape_for_urls(urls_to_test, save_history=False):
    results = []
    run_id = uuid.uuid4().hex if save_history else None

    max_workers = min(4, max(1, len(urls_to_test)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scrape_single_url, url) for url in urls_to_test]

        for future in as_completed(futures):
            results.append(future.result())

    # păstrăm ordinea mai stabilă pentru afișare
    results.sort(key=lambda x: (x["Parfum"], x["Magazin"]))

    if save_history:
        db = SessionLocal()

        for row in results:
            history_item = PriceHistory(
                watched_url_id=row["watched_url_id"],
                check_run_id=run_id,
                checked_at=row["checked_at"],
                price=row["Preț"],
                currency=row["Monedă"],
                in_stock=row["În stoc"],
                extracted_title=row["Titlu extras"],
                error_message=row["Eroare"] or None,
            )
            db.add(history_item)

        db.commit()
        db.close()

    # scoatem câmpurile interne înainte de afișare
    cleaned_results = []
    for row in results:
        cleaned_row = dict(row)
        cleaned_row.pop("watched_url_id", None)
        cleaned_row.pop("checked_at", None)
        cleaned_results.append(cleaned_row)

        cleaned_results = sorted(
        cleaned_results,
        key=lambda x: (
            x["Parfum"] or "",
            x["Magazin"] or "",
            x["Volum țintă"] or 0
        )
    )

    return cleaned_results

page = st.sidebar.radio(
    "Navigare",
    ["Colecția mea", "Parfumuri urmărite", "Istoric prețuri"]
)

if page == "Colecția mea":
    st.subheader("Colecția mea")

    with st.form("owned_perfume_form"):
        brand = st.text_input("Brand")
        name = st.text_input("Nume parfum")
        concentration = st.text_input("Concentrație (ex: EDT, EDP, Parfum)")
        volume_ml = st.number_input("Volum (ml)", min_value=0, step=1)
        store_name = st.text_input("De unde l-ai cumpărat")
        purchase_price = st.number_input("Preț plătit", min_value=0.0, step=1.0)
        purchase_date = st.date_input("Data cumpărării", value=date.today())
        notes = st.text_area("Note")
        submitted = st.form_submit_button("Salvează")

    if submitted:
        if not brand.strip() or not name.strip():
            st.error("Brand și Nume sunt obligatorii.")
        else:
            db = SessionLocal()
            perfume = OwnedPerfume(
                brand=brand.strip(),
                name=name.strip(),
                concentration=concentration.strip() or None,
                volume_ml=volume_ml if volume_ml > 0 else None,
                store_name=store_name.strip() or None,
                purchase_price=purchase_price if purchase_price > 0 else None,
                purchase_date=purchase_date,
                notes=notes.strip() or None,
            )
            db.add(perfume)
            db.commit()
            db.close()
            st.success("Parfumul a fost salvat.")
            st.rerun()

    st.divider()
    st.subheader("Parfumurile salvate")

    items = get_owned_perfumes()

    if items:
        data = [
            {
                "ID": item.id,
                "Brand": item.brand,
                "Nume": item.name,
                "Concentrație": item.concentration,
                "Volum (ml)": item.volume_ml,
                "Magazin": item.store_name,
                "Preț plătit": item.purchase_price,
                "Preț / ml": round(item.purchase_price / item.volume_ml, 2)
                if item.purchase_price is not None and item.volume_ml not in (None, 0)
                else None,
                "Data cumpărării": item.purchase_date,
                "Note": item.notes,
            }
            for item in items
        ]
        df = pd.DataFrame(data)
        df = df.sort_values(
            by=["Brand", "Nume", "Volum (ml)"],
            kind="stable"
        ).reset_index(drop=True)
        st.dataframe(df, width="stretch")

        st.divider()
        st.subheader("Șterge parfum din colecție")

        owned_options = {
            f'#{item.id} - {item.brand} - {item.name} ({item.concentration or "-"}, {item.volume_ml or "?"} ml)': item.id
            for item in items
        }

        selected_owned_label = st.selectbox(
            "Alege parfumul de șters",
            options=list(owned_options.keys()),
            key="delete_owned_select"
        )

        if st.button("Șterge parfumul din colecție", key="delete_owned_button"):
            db = SessionLocal()
            item_to_delete = db.query(OwnedPerfume).filter(
                OwnedPerfume.id == owned_options[selected_owned_label]
            ).first()

            if item_to_delete:
                db.delete(item_to_delete)
                db.commit()
                st.success("Parfumul a fost șters.")

            db.close()
            st.rerun()
    else:
        st.info("Nu ai încă parfumuri salvate.")

elif page == "Parfumuri urmărite":
    st.subheader("Parfumuri urmărite")

    with st.form("watched_perfume_form"):
        brand = st.text_input("Brand", key="watched_brand")
        name = st.text_input("Nume parfum", key="watched_name")
        concentration = st.text_input(
            "Concentrație (ex: EDT, EDP, Parfum)",
            key="watched_concentration"
        )
        volume_ml = st.number_input(
            "Volum (ml)",
            min_value=0,
            step=1,
            key="watched_volume"
        )
        desired_price = st.number_input(
            "Preț dorit",
            min_value=0.0,
            step=1.0,
            key="watched_price"
        )
        notes = st.text_area("Note", key="watched_notes")
        submitted = st.form_submit_button("Salvează parfum urmărit")

    if submitted:
        if not brand.strip() or not name.strip():
            st.error("Brand și Nume sunt obligatorii.")
        else:
            db = SessionLocal()
            perfume = WatchedPerfume(
                brand=brand.strip(),
                name=name.strip(),
                concentration=concentration.strip() or None,
                volume_ml=volume_ml if volume_ml > 0 else None,
                desired_price=desired_price if desired_price > 0 else None,
                notes=notes.strip() or None,
            )
            db.add(perfume)
            db.commit()
            db.close()
            st.success("Parfumul urmărit a fost salvat.")
            st.rerun()

    st.divider()
    st.subheader("Lista parfumurilor urmărite")

    watched_items = get_watched_perfumes()

    if watched_items:
        data = [
            {
                "ID": item.id,
                "Brand": item.brand,
                "Nume": item.name,
                "Concentrație": item.concentration,
                "Volum (ml)": item.volume_ml,
                "Preț dorit": item.desired_price,
                "Note": item.notes,
            }
            for item in watched_items
        ]
        df = pd.DataFrame(data)
        df = df.sort_values(
            by=["Brand", "Nume", "Volum (ml)"],
            kind="stable"
        ).reset_index(drop=True)
        st.dataframe(df, width="stretch")

        st.divider()
        st.subheader("Șterge parfum urmărit")

        watched_options = {
            f'#{item.id} - {item.brand} - {item.name} ({item.concentration or "-"}, {item.volume_ml or "?"} ml)': item.id
            for item in watched_items
        }

        selected_watched_label = st.selectbox(
            "Alege parfumul urmărit de șters",
            options=list(watched_options.keys()),
            key="delete_watched_select"
        )

        if st.button("Șterge parfumul urmărit", key="delete_watched_button"):
            db = SessionLocal()
            item_to_delete = db.query(WatchedPerfume).filter(
                WatchedPerfume.id == watched_options[selected_watched_label]
            ).first()

            if item_to_delete:
                db.delete(item_to_delete)
                db.commit()
                st.success("Parfumul urmărit a fost șters.")

            db.close()
            st.rerun()
    else:
        st.info("Nu ai încă parfumuri urmărite.")

    st.divider()
    st.subheader("Adaugă URL pentru un parfum urmărit")

    watched_items = get_watched_perfumes()

    if watched_items:
        perfume_options = {
            f"{item.brand} - {item.name} ({item.concentration or '-'}, {item.volume_ml or '?'} ml)": item.id
            for item in watched_items
        }

        with st.form("watched_url_form"):
            selected_label = st.selectbox(
                "Alege parfumul",
                options=list(perfume_options.keys())
            )
            shop_name = st.text_input("Magazin")
            product_url = st.text_input("URL produs")
            is_active = st.checkbox("Activ", value=True)

            submitted_url = st.form_submit_button("Salvează URL")

        if submitted_url:
            if not shop_name.strip() or not product_url.strip():
                st.error("Magazin și URL sunt obligatorii.")
            else:
                db = SessionLocal()
                watched_url = WatchedUrl(
                    watched_perfume_id=perfume_options[selected_label],
                    shop_name=shop_name.strip(),
                    product_url=product_url.strip(),
                    is_active=is_active,
                )
                db.add(watched_url)
                db.commit()
                db.close()
                st.success("URL-ul a fost salvat.")
                st.rerun()

        st.divider()
        st.subheader("URL-uri salvate")

        urls = get_watched_urls()

        if urls:
            url_data = []

            db = SessionLocal()
            for url in urls:
                perfume = db.query(WatchedPerfume).filter(
                    WatchedPerfume.id == url.watched_perfume_id
                ).first()

                perfume_name = f"{perfume.brand} - {perfume.name}" if perfume else "Necunoscut"

                url_data.append(
                    {
                        "ID": url.id,
                        "Parfum": perfume_name,
                        "Magazin": url.shop_name,
                        "URL": url.product_url,
                        "Activ": url.is_active,
                    }
                )
            db.close()

            df_urls = pd.DataFrame(url_data)
            df_urls = df_urls.sort_values(
                by=["Parfum", "Magazin"],
                kind="stable"
            ).reset_index(drop=True)
            st.dataframe(df_urls, width="stretch")

            st.divider()
            st.subheader("Șterge URL salvat")

            db = SessionLocal()
            url_options = {}
            for url in urls:
                perfume = db.query(WatchedPerfume).filter(
                    WatchedPerfume.id == url.watched_perfume_id
                ).first()

                perfume_name = f"{perfume.brand} - {perfume.name}" if perfume else "Necunoscut"
                label = f"#{url.id} - {perfume_name} - {url.shop_name}"
                url_options[label] = url.id
            db.close()

            selected_url_label = st.selectbox(
                "Alege URL-ul de șters",
                options=list(url_options.keys()),
                key="delete_url_select"
            )

            if st.button("Șterge URL-ul", key="delete_url_button"):
                db = SessionLocal()
                url_to_delete = db.query(WatchedUrl).filter(
                    WatchedUrl.id == url_options[selected_url_label]
                ).first()

                if url_to_delete:
                    db.delete(url_to_delete)
                    db.commit()
                    st.success("URL-ul a fost șters.")

                db.close()
                st.rerun()

            active_urls = [url for url in urls if url.is_active]

            if active_urls:
                st.divider()
                st.subheader("Testează pe parfumuri selectate")

                db = SessionLocal()

                perfume_ids_with_active_urls = sorted(
                    {url.watched_perfume_id for url in active_urls}
                )

                perfumes_for_testing = db.query(WatchedPerfume).filter(
                    WatchedPerfume.id.in_(perfume_ids_with_active_urls)
                ).order_by(WatchedPerfume.brand, WatchedPerfume.name).all()

                perfume_test_options = {
                    f'#{item.id} - {item.brand} - {item.name} ({item.concentration or "-"}, {item.volume_ml or "?"} ml)': item.id
                    for item in perfumes_for_testing
                }

                all_perfume_labels = list(perfume_test_options.keys())
                multiselect_key = "test_perfumes_multiselect"

                if multiselect_key not in st.session_state:
                    st.session_state[multiselect_key] = all_perfume_labels.copy()
                else:
                    st.session_state[multiselect_key] = [
                        label for label in st.session_state[multiselect_key]
                        if label in all_perfume_labels
                    ]

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Selectează toate parfumurile", key="select_all_test_perfumes"):
                        st.session_state[multiselect_key] = all_perfume_labels.copy()
                        st.rerun()

                with col2:
                    if st.button("Curăță selecția", key="clear_test_perfumes"):
                        st.session_state[multiselect_key] = []
                        st.rerun()

                selected_perfume_labels = st.multiselect(
                    "Alege parfumurile pentru testare",
                    options=all_perfume_labels,
                    key=multiselect_key
                )

                selected_perfume_ids = {
                    perfume_test_options[label]
                    for label in selected_perfume_labels
                }

                urls_to_test = [
                    url for url in active_urls
                    if url.watched_perfume_id in selected_perfume_ids
                ]

                if not selected_perfume_labels:
                    st.info("Selectează cel puțin un parfum pentru testare.")
                else:
                    st.write(
                        f"Vor fi testate {len(urls_to_test)} URL-uri active pentru {len(selected_perfume_labels)} parfum(uri)."
                    )

                    button_col1, button_col2 = st.columns(2)

                    with button_col1:
                        test_only_clicked = st.button(
                            "Testează fără salvare",
                            key="test_selected_perfumes_button"
                        )

                    with button_col2:
                        save_clicked = st.button(
                            "Verifică și salvează prețurile",
                            key="save_selected_perfumes_button"
                        )

                    if test_only_clicked:
                        st.session_state["last_scrape_results"] = run_scrape_for_urls(
                            urls_to_test,
                            save_history=False
                        )

                    if save_clicked:
                        st.session_state["last_scrape_results"] = run_scrape_for_urls(
                            urls_to_test,
                            save_history=True
                        )
                        st.success("Verificările au fost salvate în istoric.")

                db.close()

                if "last_scrape_results" in st.session_state:
                    results = st.session_state["last_scrape_results"]

                    st.divider()
                    st.subheader("Rezultate verificare")

                    df_results = pd.DataFrame(results)
                    st.dataframe(df_results, width="stretch")

                    for row in results:
                        if row["Eroare"]:
                            st.error(f'{row["Parfum"]} / {row["Magazin"]}: {row["Eroare"]}')
            else:
                st.info("Nu ai URL-uri active pentru testare.")
        else:
            st.info("Nu ai încă URL-uri salvate.")
    else:
        st.info("Adaugă mai întâi cel puțin un parfum urmărit.")

elif page == "Istoric prețuri":
    st.subheader("Istoric prețuri")

    history_records = build_history_records()

    if history_records:
        perfume_options_map = {}
        for record in history_records:
            if record["perfume_id"] is not None:
                perfume_options_map[record["perfume_label"]] = record["perfume_id"]

        filter_options = ["Toate parfumurile"] + sorted(perfume_options_map.keys())

        selected_perfume_filter = st.selectbox(
            "Filtrează după parfum",
            options=filter_options,
            key="history_perfume_filter"
        )

        if selected_perfume_filter == "Toate parfumurile":
            filtered_records = history_records
            selected_perfume_id = None
        else:
            selected_perfume_id = perfume_options_map[selected_perfume_filter]
            filtered_records = [
                record for record in history_records
                if record["perfume_id"] == selected_perfume_id
            ]

        if filtered_records:
            grouped_runs = defaultdict(list)
            for record in filtered_records:
                grouped_runs[record["run_id"]].append(record)

            sorted_runs = sorted(
                grouped_runs.items(),
                key=lambda item: max(
                    rec["checked_at_dt"] or datetime.min for rec in item[1]
                ),
                reverse=True
            )

            st.divider()
            st.subheader("Salvări separate")

            for run_id, run_records in sorted_runs:
                run_records_sorted = sorted(
                    run_records,
                    key=lambda rec: (rec["checked_at_dt"] or datetime.min, rec["perfume_label"], rec["shop_name"] or "")
                )

                run_time = max(rec["checked_at_dt"] or datetime.min for rec in run_records_sorted)
                run_time_label = run_time.strftime("%Y-%m-%d %H:%M:%S") if run_time != datetime.min else "Necunoscut"

                st.markdown(f"### Salvare din {run_time_label}")

                changed_rows = [
                    rec for rec in run_records_sorted
                    if rec["price_change"] not in ("Prima valoare", "Neschimbat", "Fără preț")
                ]

                if changed_rows:
                    change_lines = [
                        f'{rec["perfume_label"]} / {rec["shop_name"]}: {rec["price_change"]}'
                        for rec in changed_rows
                    ]
                    st.info("Schimbări de preț detectate:\n\n" + "\n".join(change_lines))

                run_df = pd.DataFrame([
                    {
                        "Parfum": rec["perfume_label"],
                        "Volum țintă (ml)": rec["target_volume_ml"],
                        "Magazin": rec["shop_name"],
                        "Preț": rec["price"],
                        "Monedă": rec["currency"],
                        "În stoc": rec["in_stock"],
                        "Schimbare față de ultima verificare": rec["price_change"],
                        "Titlu extras": rec["extracted_title"],
                        "Eroare": rec["error_message"],
                    }
                    for rec in run_records_sorted
                ])
                
                run_df = run_df.sort_values(
                    by=["Parfum", "Magazin", "Volum țintă (ml)"],
                    kind="stable"
                ).reset_index(drop=True)
                
                st.dataframe(run_df, width="stretch")

            if selected_perfume_id is not None:
                st.divider()
                st.subheader(f"Evoluție completă pentru {selected_perfume_filter}")

                perfume_timeline = sorted(
                    filtered_records,
                    key=lambda rec: (rec["checked_at_dt"] or datetime.min)
                )

                timeline_df = pd.DataFrame([
                    {
                        "Data verificării": rec["checked_at_display"],
                        "Magazin": rec["shop_name"],
                        "Volum țintă (ml)": rec["target_volume_ml"],
                        "Preț": rec["price"],
                        "Monedă": rec["currency"],
                        "În stoc": rec["in_stock"],
                        "Schimbare față de ultima verificare": rec["price_change"],
                        "Titlu extras": rec["extracted_title"],
                        "Eroare": rec["error_message"],
                    }
                    for rec in perfume_timeline
                ])

                st.dataframe(timeline_df, width="stretch")
        else:
            st.info("Nu există înregistrări pentru filtrul selectat.")
    else:
        st.info("Nu ai încă verificări salvate în istoric.")