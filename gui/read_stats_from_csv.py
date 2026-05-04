import csv
import json
import sys
import os

def read_stats_from_csv(filepath):
    data = {}
    with open(filepath, mode='r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            data[row['Name']] = row

    return data


def save_stats_as_json(csv_filepath, json_filepath=None):
    """Convert CSV to JSON and save. Returns the JSON filepath."""
    if json_filepath is None:
        json_filepath = os.path.splitext(csv_filepath)[0] + '.json'

    data = read_stats_from_csv(csv_filepath)
    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return json_filepath


def load_stats_from_json(json_filepath):
    """Load stats from JSON file."""
    with open(json_filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: %s [filepath]" % sys.argv[0])
    else:
        data = read_stats_from_csv(sys.argv[1])
        print(f"Loaded {len(data)} monster stats")
