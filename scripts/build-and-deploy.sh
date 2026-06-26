#!/bin/bash
# ============================================
# AgentScope AI 问答系统 - Docker 构建与部署脚本
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

print_usage() {
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  build       构建 Docker 镜像"
    echo "  up          启动所有服务（前台）"
    echo "  down        停止所有服务"
    echo "  restart     重启所有服务"
    echo "  logs        查看日志"
    echo "  ps          查看服务状态"
    echo "  clean       清理所有数据卷"
    echo ""
    echo "示例:"
    echo "  $0 build     # 构建镜像"
    echo "  $0 up -d     # 后台启动所有服务"
    echo "  $0 logs app  # 查看 app 服务的日志"
}

# 检查 docker 和 docker-compose
check_docker() {
    if ! command -v docker &>/dev/null; then
        echo "错误: 未找到 docker 命令，请先安装 Docker"
        exit 1
    fi
    if ! docker compose version &>/dev/null; then
        echo "错误: 未找到 docker compose 插件，请安装 Docker Compose v2"
        exit 1
    fi
}

case "${1:-help}" in
    build)
        check_docker
        echo ">>> 构建 AgentScope AI 问答系统镜像..."
        docker compose build app
        echo ">>> 构建完成"
        ;;
    up)
        check_docker
        shift
        echo ">>> 启动所有服务..."
        docker compose up "$@"
        ;;
    down)
        check_docker
        echo ">>> 停止所有服务..."
        docker compose down
        echo ">>> 服务已停止"
        ;;
    restart)
        check_docker
        echo ">>> 重启所有服务..."
        docker compose restart
        echo ">>> 服务已重启"
        ;;
    logs)
        check_docker
        shift
        docker compose logs "$@"
        ;;
    ps)
        check_docker
        docker compose ps
        ;;
    clean)
        check_docker
        echo ">>> 警告: 这将删除所有数据卷（Redis、PostgreSQL、工作区数据）"
        read -p "确认删除? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker compose down -v
            echo ">>> 数据卷已清理"
        else
            echo ">>> 已取消"
        fi
        ;;
    help|*)
        print_usage
        ;;
esac