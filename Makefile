.PHONY: install test build clean

-include .env
export

install:
	pip install -r requirements.txt

test:
	python -m unittest discover -s src -p "*_unittest.py" -t .

build_national:
	python -m src.main --path $(NATIONAL_SERIES_FILE) --series-type 1 --start-year 2000 --end-year 2005 --series-count 1
	
build_state:
	python -m src.main --path $(STATE_SERIES_FILE) --series-type 2 --start-year 2000 --end-year 2005 --series-count 1