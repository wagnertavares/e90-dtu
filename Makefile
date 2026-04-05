HOST   = wtavares@hswrpi33.local
REMOTE = /home/wtavares/e90-dtu
PORT   = /dev/ttyUSB0

.PHONY: deploy test run shell

## Copy source files to the remote host
deploy:
	ssh $(HOST) "mkdir -p $(REMOTE)"
	scp dtu.py test_hw.py $(HOST):$(REMOTE)/

## Run hardware-in-the-loop tests on the remote host
test: deploy
	ssh $(HOST) "python3 $(REMOTE)/test_hw.py --port $(PORT)"

## Open an interactive session with dtu.py on the remote host
run: deploy
	ssh -t $(HOST) "python3 $(REMOTE)/dtu.py --port $(PORT)"

## SSH into the remote host
shell:
	ssh -t $(HOST)
