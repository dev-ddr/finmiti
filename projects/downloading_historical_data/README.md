# Imports


```python
import os
import yaml
import finmetry as fm
```

# All filepaths


```python
creds_filepath = "../../configs/5paisa_creds.yaml.example"
local_data_foldpath = "../../data/historical_data"
```

# Initializing Client


```python
creds = yaml.safe_load(open(creds_filepath))
```


```python
client = fm.clients.client_5paisa.Client5paisa(totp=input("give totp from the autheticator app"), **creds)
```

# Downloading the data for a stock


```python
symbol = "IDEA"
start_date, end_date = "2018-01-01", "2026-01-14"
interval = fm.constants.INTERVAL.one_day
```


```python
s1 = fm.Stock(symbol)
data = client.download_historical_data(s1,start=start_date, end=end_date, interval=interval)
data.info()
```

    <class 'pandas.core.frame.DataFrame'>
    DatetimeIndex: 1992 entries, 2018-01-01 00:00:00 to 2026-01-14 09:15:00
    Data columns (total 5 columns):
     #   Column  Non-Null Count  Dtype  
    ---  ------  --------------  -----  
     0   Open    1992 non-null   float64
     1   High    1992 non-null   float64
     2   Low     1992 non-null   float64
     3   Close   1992 non-null   float64
     4   Volume  1992 non-null   int64  
    dtypes: float64(4), int64(1)
    memory usage: 93.4 KB


# Saving the data

The data is saved as month wise files.


```python
s1.save_historical_data(data=data, interval=interval, local_data_foldpath=local_data_foldpath, overwrite=False)
```

# Loading the data from local storage


```python
start_date, end_date = "2025-01-01", "2026-01-14"
interval = fm.constants.INTERVAL.one_day

data = s1.load_historical_data(start=start_date, end=end_date, interval=interval, local_data_foldpath=local_data_foldpath)
data.info()
```

    <class 'pandas.core.frame.DataFrame'>
    DatetimeIndex: 258 entries, 2025-01-01 to 2026-01-13
    Data columns (total 5 columns):
     #   Column  Non-Null Count  Dtype  
    ---  ------  --------------  -----  
     0   Open    258 non-null    float64
     1   High    258 non-null    float64
     2   Low     258 non-null    float64
     3   Close   258 non-null    float64
     4   Volume  258 non-null    int64  
    dtypes: float64(4), int64(1)
    memory usage: 12.1 KB


---
---
