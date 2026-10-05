import pandas as pd

def test_highest_score_gets_d1():
    """
    Test asserting which decile label the highest score gets.
    For direction=1, the highest scores get the lowest ranks (rank 1),
    which fall into the first qcut bin (D1).
    """
    # 100 stocks, scores 1 to 100
    scores = pd.Series(
        data=[float(i) for i in range(1, 101)],
        index=[f"ISIN_{i}" for i in range(1, 101)],
    )
    
    # Simulate decile.py / run_factors.py logic for direction=1
    asc = False  # direction = 1 means ascending = False
    ranks = scores.rank(method="first", ascending=asc)
    deciles = pd.qcut(ranks, q=10, labels=range(1, 11))
    
    # Highest score is ISIN_100 (score=100.0)
    assert scores["ISIN_100"] == 100.0
    
    # Its decile label must be 1
    assert deciles["ISIN_100"] == 1

