"""Offline data tools for the ChessMate engine.

These scripts process the Kaggle Lichess CSV to produce:
  - normalized games  (parse_kaggle_games.py)
  - an opening book   (build_opening_book.py)
  - labeled moves     (label_moves.py)
  - puzzles           (extract_puzzles.py)
  - small policy NN   (train_policy_small.py)

python-chess is permitted here (only here) for PGN/FEN reconstruction.
"""
