import argparse
import multiprocessing


def main():
    parser = argparse.ArgumentParser(description="SAGSIN FL local research console")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
