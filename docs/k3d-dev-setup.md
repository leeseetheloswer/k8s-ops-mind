# k3d 本地开发测试环境搭建手册

> 环境：Ubuntu 24.04 LTS on WSL2 / x86_64
> 网络：国内环境，需走代理访问 Docker Hub

---

## 一、安装 Docker

### 1.1 安装前置依赖

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
```

### 1.2 添加 Docker GPG Key

```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

### 1.3 添加 Docker 软件源

> ⚠️ **坑：sources.list 换行问题**
>
> 直接用 `echo "..." | sudo tee` 从终端多行粘贴时，`$(lsb_release -cs)` 会被换行符截断，导致文件格式损坏：
> ```
> E: Malformed entry 1 in list file /etc/apt/sources.list.d/docker.list (Suite)
> ```
> **解决办法**：用 `sudo bash -c '...'` 将内容写死，避免换行：

```bash
sudo bash -c 'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list'
```

验证文件内容为一行：

```bash
cat /etc/apt/sources.list.d/docker.list
# 应输出：deb [arch=amd64 ...] https://... noble stable
```

### 1.4 安装 Docker Engine

```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

> ⚠️ **坑：python3-venv 缺失**
>
> Ubuntu 24.04 创建虚拟环境报错 `ensurepip is not available`，需要先安装：
> ```bash
> sudo apt install python3.12-venv -y
> ```

### 1.5 配置用户权限

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 1.6 启动 Docker（WSL2 需手动启动）

```bash
sudo service docker start
docker info   # 验证正常
```

### 1.7 配置代理（国内必须）

给 Docker daemon 配置代理，用于拉取镜像：

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf > /dev/null <<EOF
[Service]
Environment="HTTP_PROXY=http://192.168.128.1:10809"
Environment="HTTPS_PROXY=http://192.168.128.1:10809"
Environment="NO_PROXY=localhost,127.0.0.1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

> 代理地址 `192.168.128.1` 是 WSL2 访问 Windows 宿主机的默认网关，端口根据实际代理软件调整。

---

## 二、安装 kubectl

```bash
curl -LO "https://dl.k8s.io/release/$(curl -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl
kubectl version --client
```

---

## 三、安装 k3d

```bash
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
k3d version
```

---

## 四、创建集群

### 4.1 基础创建

```bash
k3d cluster create dev
kubectl cluster-info
```

### 4.2 国内网络问题

> ⚠️ **坑：k3d 拉取镜像失败**
>
> k3d 集群节点本质是 Docker 容器，容器内的 containerd 访问 Docker Hub 走的是容器自己的网络，不会自动继承宿主机的代理设置。因此 k3d 自身可以创建成功，但内部 Pod 所需镜像（包括 `rancher/mirrored-pause`）无法拉取。
>
> **报错特征**：
> ```
> Failed to create pod sandbox: failed to pull image "rancher/mirrored-pause:3.6": dial tcp ...: i/o timeout
> ```

---

## 五、解决镜像拉取问题（国内核心步骤）

### 5.1 在宿主机用 Docker 拉取镜像

宿主机 Docker daemon 已配置好代理，直接拉取：

```bash
docker pull rancher/mirrored-pause:3.6
docker pull nginx
docker pull redis
```

### 5.2 将镜像导入 containerd（关键步骤）

> ⚠️ **坑：k3d image import 对 pause 镜像无效**
>
> `k3d image import` 命令走的是 k3d 自己的传输机制，pause 镜像由 CRI 在更底层直接调用，无法通过该命令导入。
>
> **必须**直接操作 containerd 的 `k8s.io` namespace：

```bash
# 导出镜像为 tar
docker save rancher/mirrored-pause:3.6 -o /tmp/pause.tar
docker save nginx -o /tmp/nginx.tar
docker save redis -o /tmp/redis.tar

# 复制进 k3d 节点容器
docker cp /tmp/pause.tar k3d-dev-server-0:/tmp/pause.tar
docker cp /tmp/nginx.tar  k3d-dev-server-0:/tmp/nginx.tar
docker cp /tmp/redis.tar  k3d-dev-server-0:/tmp/redis.tar

# 导入到 containerd 的 k8s.io namespace
docker exec k3d-dev-server-0 ctr -n k8s.io images import /tmp/pause.tar
docker exec k3d-dev-server-0 ctr -n k8s.io images import /tmp/nginx.tar
docker exec k3d-dev-server-0 ctr -n k8s.io images import /tmp/redis.tar

# 验证
docker exec k3d-dev-server-0 ctr -n k8s.io images ls | grep pause
```

### 5.3 部署测试资源

```bash
kubectl create deployment nginx --image=nginx
kubectl expose deployment nginx --port=80 --type=ClusterIP

kubectl create deployment redis --image=redis
kubectl expose deployment redis --port=6379 --type=ClusterIP
```

### 5.4 修复 imagePullPolicy

> ⚠️ **坑：latest 镜像默认 Always 拉取策略**
>
> Kubernetes 对 `latest` 标签的镜像默认 `imagePullPolicy: Always`，即使本地有镜像也会尝试从远程拉取，导致 `ErrImagePull`。
>
> **必须**将策略改为 `IfNotPresent`：

```bash
kubectl patch deployment nginx -p '{"spec":{"template":{"spec":{"containers":[{"name":"nginx","imagePullPolicy":"IfNotPresent"}]}}}}'
kubectl patch deployment redis -p '{"spec":{"template":{"spec":{"containers":[{"name":"redis","imagePullPolicy":"IfNotPresent"}]}}}}'
```

等待 Pod 就绪：

```bash
kubectl get pods -w
# nginx-xxx   1/1   Running   0   10s
# redis-xxx   1/1   Running   0   8s
```

---

## 六、以后新增镜像的标准流程

每次需要在集群中使用新镜像时，重复以下步骤：

```bash
IMAGE=your-image:tag

# 1. 宿主机拉取
docker pull $IMAGE

# 2. 导出并导入 containerd
docker save $IMAGE -o /tmp/img.tar
docker cp /tmp/img.tar k3d-dev-server-0:/tmp/img.tar
docker exec k3d-dev-server-0 ctr -n k8s.io images import /tmp/img.tar

# 3. 部署时指定 IfNotPresent
kubectl set image deployment/<name> <container>=$IMAGE
kubectl patch deployment <name> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container>","imagePullPolicy":"IfNotPresent"}]}}}}'
```

---

## 七、常用命令速查

```bash
# 集群管理
k3d cluster list
k3d cluster stop dev
k3d cluster start dev
k3d cluster delete dev

# 查看资源
kubectl get pods -A
kubectl get nodes
kubectl describe pod <name>

# 查看 containerd 中的镜像
docker exec k3d-dev-server-0 ctr -n k8s.io images ls

# 重启 deployment
kubectl rollout restart deployment <name>

# 端口占用时清理残留进程
pkill -f uvicorn; pkill -f vite
```

---

## 八、问题排查速查

| 现象 | 原因 | 解决 |
|------|------|------|
| `Malformed entry` apt 报错 | sources.list 写入时换行 | 用 `sudo bash -c 'echo ... > file'` 写入 |
| k3d 创建时拉镜像超时 | containerd 无代理 | 宿主机拉好后 `ctr -n k8s.io images import` 导入 |
| Pod 一直 `ContainerCreating` | pause 镜像缺失 | 单独导入 `rancher/mirrored-pause:3.6` |
| Pod `ErrImagePull` / `ImagePullBackOff` | imagePullPolicy=Always | patch deployment 改为 `IfNotPresent` |
| 端口 8000/5173 被占用 | 上次服务未退出 | `pkill -f uvicorn; pkill -f vite` |
