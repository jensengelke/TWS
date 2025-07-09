from concurrent.futures import ThreadPoolExecutor
import functools

def get_historic_data(param):
    # Simulate work (e.g. API call or DB fetch)
    return f"data_for_{param}"

def process_result(param, result):
    print(f"Processing result for {param}: {result}")

def handle_result(param, future):
    try:
        result = future.result()
        process_result(param, result)
    except Exception as e:
        print(f"Error processing {param}: {e}")

def main():
    params = ['AAPL', 'MSFT', 'GOOG']
    with ThreadPoolExecutor(max_workers=3) as executor:
        for param in params:
            future = executor.submit(get_historic_data, param)
            # Use functools.partial to bind `param` to the callback
            future.add_done_callback(functools.partial(handle_result, param))

if __name__ == "__main__":
    main()