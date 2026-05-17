FROM python:alpine

RUN apk add aws-cli

RUN adduser -D -h /home/python python
USER python
WORKDIR /home/python

RUN pip3 install telethon==1.43.2 openai==2.33.0
COPY telegram-ai-message-analyzer.sh telegram-ai-message-analyzer.py /home/python

CMD sh telegram-ai-message-analyzer.sh
