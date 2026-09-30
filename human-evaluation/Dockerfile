FROM python:3.12-slim
WORKDIR /evaluation
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py export.py ./
COPY web/dist/ web/dist/
RUN useradd -u 1000 -m evaluator && mkdir data && chown evaluator:evaluator data
USER evaluator
EXPOSE 8080
CMD ["uvicorn", "server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
