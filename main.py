import ssl
import multiprocessing
from config import vsphere
from proxy_app import create_flask_app

def run_app(app, port):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('certs/server.crt', 'certs/server.key')
    app.run(host='0.0.0.0', port=port, ssl_context=context)

if __name__ == '__main__':
    processes = []

    for vm in vsphere['vms']:
        app = create_flask_app(vsphere, vm)
        port = vm['port']
        print(f"Starting proxy for VM {vm['vmId']} on port {port}")
        p = multiprocessing.Process(target=run_app, args=(app, port))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()