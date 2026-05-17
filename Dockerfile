FROM public.ecr.aws/lambda/python

RUN pip3 install telethon==1.43.2 openai==2.33.0 --target "${LAMBDA_TASK_ROOT}"
COPY telegram-ai-message-analyzer.py ${LAMBDA_TASK_ROOT}

CMD ["telegram-ai-message-analyzer.main"]
