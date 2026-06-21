import datetime as dtm

def str_to_dtm(timestring:str)->dtm.datetime:
    return dtm.datetime.strptime(timestring, "%Y-%m-%d")

def dtm_to_str(timestamp:dtm.datetime)->str:
    return timestamp.strftime("%Y-%m-%d")