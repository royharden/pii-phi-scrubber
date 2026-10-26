FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
LABEL agentports.project="m7" agentports.instance="r03-rv2" agentports.owner="0017"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY evals/requirements-docker.txt /app/evals/requirements-docker.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /app/evals/requirements-docker.txt
COPY src/ /app/src/
COPY scripts/_common.py scripts/demo.py scripts/eval.py /app/scripts/
COPY data-development/public-fictional.json /app/data-development/public-fictional.json
COPY evals/public_eval.py /app/evals/public_eval.py
USER 65532:65532
ENTRYPOINT ["python", "/app/evals/public_eval.py"]
CMD ["--out", "/tmp/m7-public-eval"]
