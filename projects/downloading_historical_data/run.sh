#!/bin/bash

# python download_for_multiple_stocks.py \
#     --symbols_list_filepath "/home/darshan-rathod/Desktop/synodrive/market_strategies/data/list_of_symbols/futures_traded_symbols.txt" \
#     --local_data_foldpath "/home/darshan-rathod/Desktop/synodrive/market_strategies/data/historical_data" \
#     --creds_filepath "/home/darshan-rathod/Desktop/synodrive/market_strategies/configs/5paisa_creds_account2.yaml" \
#     --start_date "2018-01-01" \
#     --end_date "2026-02-22" \
#     --interval "fifteen_min" \
#     --overwrite "true" \


python download_for_multiple_stocks.py \
    --symbols_list_filepath "/home/darshan-rathod/Desktop/synodrive/market_strategies/data/list_of_symbols/nifty_500_symbols.txt" \
    --local_data_foldpath "/home/darshan-rathod/Desktop/synodrive/market_strategies/data/historical_data" \
    --creds_filepath "/home/darshan-rathod/Desktop/synodrive/market_strategies/configs/5paisa_creds_account2.yaml" \
    --start_date "2018-01-01" \
    --end_date "2026-03-06" \
    --interval "one_day" \
    --overwrite "true" \
