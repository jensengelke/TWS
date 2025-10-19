import argparse
import pandas as pd

import xml.etree.ElementTree as ET

def parse_open_positions(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()
    print(f"Root tag: {root.tag}")
    open_positions = root.findall('FlexStatements/FlexStatement/OpenPositions')
    if open_positions is None:
        return pd.DataFrame()  # Return empty DataFrame if not found

    if len(open_positions) == 0 or len(open_positions) > 1:
        print(f"Expected exactly one OpenPositions element, but found {len(open_positions)}")
        raise ValueError("Invalid XML structure")
    
    data = []
    for pos in open_positions[0].findall("OpenPosition"):
        attr_dict = {}
        for attr_name, attr_value in pos.attrib.items():
            attr_dict[attr_name] = attr_value
        data.append(attr_dict)
    return pd.DataFrame(data)

def main():
    parser = argparse.ArgumentParser(description="Process input and output files.")
    parser.add_argument('-i', '--input', help='Path to the input file', default="C:\\Users\\jense\\Downloads\\Journal.xml")
    parser.add_argument('-o', '--output', help='Path to the output file', default="C:\\Users\\jense\\Downloads\\Journal.csv")
    args = parser.parse_args()

    print(f"Input file: {args.input}")
    print(f"Output file: {args.output}")

    df = parse_open_positions(args.input)
    print(df)

if __name__ == "__main__":
    main()