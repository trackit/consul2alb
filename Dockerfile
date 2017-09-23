FROM python:2-alpine
MAINTAINER victor@trackit.io

RUN pip install \
	boto3==1.4.4 \
	python-consul==0.7.0
COPY consul2alb.py ./consul2alb.py
CMD ./consul2alb.py
