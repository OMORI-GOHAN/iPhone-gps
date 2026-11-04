"""Read-only check; service availability does not prove USB driver readiness."""


def component_status():
    import psutil
    try:
        service = psutil.win_service_get('Apple Mobile Device Service')
        status = service.status()
    except psutil.NoSuchProcess:
        return ('未找到 Apple Mobile Device Service；运行 iphone-gps setup --install '
                '自动获取并安装 Apple Mobile Device Support，无需完整 iTunes。')
    except psutil.AccessDenied:
        return '无法读取 Apple Mobile Device Service 状态；请检查服务访问权限。'
    return f'Apple Mobile Device Service：{status}；USB 驱动及手机连接请运行 devices 检查。'
