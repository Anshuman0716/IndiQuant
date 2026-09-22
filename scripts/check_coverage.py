import duckdb
from pathlib import Path

lakehouse_dir = Path("data/silver")
if not lakehouse_dir.exists():
    print(f"Lakehouse directory {lakehouse_dir.absolute()} does not exist.")
else:
    tables = [p.name for p in lakehouse_dir.iterdir() if p.is_dir()]
    print("Lakehouse Coverage Report:\n")
    for table in tables:
        table_path = (lakehouse_dir / table / "**/*.parquet").as_posix()
        try:
            with duckdb.connect() as con:
                # Get total rows, min date, max date, distinct ISINs
                query = f"""
                SELECT 
                    COUNT(*) as total_rows,
                    COUNT(DISTINCT isin) as distinct_isins
                FROM read_parquet('{table_path}', hive_partitioning=true, union_by_name=true)
                """
                res = con.execute(query).fetchone()
                
                # Some tables might have 'date', some might have 'knowledge_date' or 'ex_date'
                date_col = 'date'
                if table == 'corporate_actions':
                    date_col = 'ex_date'
                elif table in ['fundamentals', 'shareholding', 'index_membership']:
                    date_col = 'knowledge_date' if table != 'index_membership' else 'valid_from'
                
                try:
                    date_query = f"""
                    SELECT 
                        MIN(CAST({date_col} AS DATE)) as min_date,
                        MAX(CAST({date_col} AS DATE)) as max_date
                    FROM read_parquet('{table_path}', hive_partitioning=true, union_by_name=true)
                    """
                    date_res = con.execute(date_query).fetchone()
                    min_date, max_date = date_res
                except Exception:
                    min_date, max_date = None, None

                print(f"Table: {table}")
                print(f"  Total Rows: {res[0]}")
                print(f"  Distinct ISINs: {res[1]}")
                print(f"  Date Range: {min_date} to {max_date}")
                print("-" * 40)
        except Exception as e:
            print(f"Table: {table} - Error reading: {e}")
            print("-" * 40)
