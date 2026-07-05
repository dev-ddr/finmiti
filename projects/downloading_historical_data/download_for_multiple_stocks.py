import os
import yaml
import finmetry as fm


def client_5paisa_login(creds: fm.clients.client_5paisa.Client5paisaCred)->fm.clients.client_5paisa:
    client = fm.clients.client_5paisa.Client5paisa(totp=input("give totp from the autheticator app: "), **creds)
    return client



if __name__ == "__main__":
    PID = os.getpid()
    print(f"PID: {PID}")
    import argparse

    parser = argparse.ArgumentParser(description="Downloading the data")
    parser.add_argument("--symbols_list_filepath", type=str, default="/home/darshan-rathod/Desktop/synodrive/ddr_modules/finmetry/projects/downloading_historical_data/symbols_list1.txt", help="Path of symbol's list file")
    parser.add_argument("--local_data_foldpath", type=str, default="/home/darshan-rathod/Desktop/synodrive/ddr_modules/finmetry/data/historical_data", help="Path to the local data folder")
    parser.add_argument("--creds_filepath", type=str, default="/home/darshan-rathod/Desktop/synodrive/discipline_is_the_key/configs/5paisa_creds_account2.yaml", help="Path to the 5paisa config file")
    parser.add_argument("--start_date", type=str, help="Start date for the data")
    parser.add_argument("--end_date", type=str, help="End date for the data")
    parser.add_argument("--interval", type=str, default="one_day", help="End date for the data")
    parser.add_argument("--overwrite", type=str, default="false", help="overwrite the data or not")

    args = parser.parse_args()
    symbols_filepath = args.symbols_list_filepath
    local_data_foldpath = args.local_data_foldpath
    creds_filepath = args.creds_filepath
    start_date = args.start_date
    end_date = args.end_date
    interval = args.interval

    if args.overwrite.lower() == 'true':
        overwrite = True
    elif args.overwrite.lower() == 'false':
        overwrite = False
    else:
        raise ValueError("overwrite argument must either be true or false")

    with open(symbols_filepath, 'r') as f:
        symbols = [line.strip() for line in f if line.strip()]
    extra_symbols = ['NIFTY']
    
    interval = fm.constants.INTERVAL[interval]
    creds = yaml.safe_load(open(creds_filepath,"r"))
    
    ### logging in client
    client = client_5paisa_login(creds=creds)

    ### downloading in loop
    for sym in symbols+extra_symbols:
        try:
            print(f"downloading the data for {sym}")
            s1 = fm.Stock(sym)
            data = client.download_historical_data(s1,start=start_date, end=end_date, interval=interval)
            s1.save_historical_data(data=data, interval=interval, local_data_foldpath=local_data_foldpath, overwrite=overwrite)
        except KeyboardInterrupt:
            raise  # DO NOT swallow Ctrl+C
        except Exception as e:
            print(f"[ERROR] {sym}: {e}")

