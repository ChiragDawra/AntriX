import pandas as pd
fires = pd.read_csv("firms_labeled.csv")
print(fires["label"].value_counts())
