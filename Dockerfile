# 国内网络构建时可覆盖基础镜像，例如：
#   docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim .
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 国内网络构建时可换成镜像源，例如：
#   docker build --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX=https://pypi.org/simple

# 系统依赖：tzdata 用于时区
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl \
 && rm -rf /var/lib/apt/lists/* \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX} -r requirements.txt

COPY app ./app

# 配置和数据通过卷挂载
VOLUME ["/config", "/data"]

# 非 root 用户运行
# chmod a+rX 是必需的：若构建上下文里的文件权限是 000（例如经 zip 解压后），
# 构建阶段以 root 运行看不出问题，但运行时非 root 用户会读不到 .py 而崩溃。
RUN useradd -u 1000 -m appuser \
 && chown -R appuser:appuser /app \
 && chmod -R a+rX /app
USER appuser

CMD ["python", "-m", "app.main", "/config/config.yaml"]
