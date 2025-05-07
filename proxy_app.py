from flask import Flask, request, jsonify
from threading import Thread
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl as pyvmomi_ssl
import urllib3
import requests
import time
import base64

from vmware.vapi.vsphere.client import create_vsphere_client
from com.vmware.vcenter_client import VM
from com.vmware.vcenter.vm.hardware_client import Cdrom, Boot

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_flask_app(global_config, vm_config):
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    vm_id = vm_config['vmId']

    def create_client():
        auth = request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("basic "):
            raise ValueError("Missing or invalid Authorization header")

        try:
            auth_decoded = base64.b64decode(auth.split(" ")[1]).decode("utf-8")
            username, password = auth_decoded.split(":", 1)
        except Exception:
            raise ValueError("Invalid Basic Auth format")

        session = requests.Session()
        session.verify = False

        return create_vsphere_client(
            server=global_config['host'],
            username=username,
            password=password,
            session=session
        )

    def get_vm_power_state():
        try:
            client = create_client()
            power = client.vcenter.vm.Power.get(vm_id)
            state_map = {
                'POWERED_ON': 'On',
                'POWERED_OFF': 'Off',
                'SUSPENDED': 'Off'
            }
            return state_map.get(str(power.state), 'Off')
        except Exception as e:
            print(f"Error getting VM power state: {str(e)}")
            return 'Off'

    def call_vsphere_api(action):
        client = create_client()
        power = client.vcenter.vm.Power

        print(f"\n=== vSphere API Call ===\nAction: {action}")

        if action == 'start':
            power.start(vm_id)
        elif action == 'stop':
            power.stop(vm_id)
        elif action == 'reset':
            power.reset(vm_id)
        else:
            raise ValueError("Invalid action")

    def auto_answer_vm_question():
        def _answer():
            time.sleep(2)
            try:
                context = pyvmomi_ssl._create_unverified_context()
                si = SmartConnect(
                    host=global_config['host'],
                    user=global_config['username'],
                    pwd=global_config['password'],
                    sslContext=context
                )
                content = si.RetrieveContent()
                vm = None
                for dc in content.rootFolder.childEntity:
                    for entity in dc.vmFolder.childEntity:
                        if isinstance(entity, vim.VirtualMachine) and entity._moId == vm_id:
                            vm = entity
                            break

                if vm is None:
                    print("VM not found to answer question")
                    return

                for _ in range(10):
                    question = vm.runtime.question
                    if question:
                        print(f"VM question detected: {question.text}")
                        for choice in question.choice.choiceInfo:
                            if choice.label.lower() in ['button.yes', 'button.sí', 'button.si']:
                                vm.AnswerVM(question.id, choice.key)
                                print(f"Answered with: {choice.label}")
                                return
                    time.sleep(5)

            except Exception as e:
                print(f"Error answering VM question: {e}")
            finally:
                try:
                    Disconnect(si)
                except:
                    pass

        Thread(target=_answer).start()
            
    @app.before_request
    def log_request():
        print('\n=== Incoming Request ===')
        print(f"{request.method} {request.url}")
        print("Headers:", dict(request.headers))
        print("Body:", request.get_data(as_text=True))

    @app.after_request
    def log_response(response):
        print('\n=== Outgoing Response ===')
        print('Status:', response.status)
        print('Body:', response.get_data(as_text=True))
        return response

    @app.route('/redfish/v1', methods=['GET'])
    def redfish_root():
        return jsonify({
            '@odata.context': '/redfish/v1/$metadata#ServiceRoot',
            '@odata.id': '/redfish/v1',
            '@odata.type': '#ServiceRoot.v1_5_0.ServiceRoot',
            'Id': 'RootService',
            'Name': 'Root Service',
            'Systems': {'@odata.id': '/redfish/v1/Systems'},
            'Chassis': {'@odata.id': '/redfish/v1/Chassis'},
            'Managers': {'@odata.id': '/redfish/v1/Managers'}
        })

    @app.route('/redfish/v1/Systems', methods=['GET'])
    def redfish_systems():
        return jsonify({
            '@odata.context': '/redfish/v1/$metadata#ComputerSystemCollection',
            '@odata.id': '/redfish/v1/Systems',
            '@odata.type': '#ComputerSystemCollection.ComputerSystemCollection',
            'Name': 'Computer System Collection',
            'Members@odata.count': 1,
            'Members': [{ '@odata.id': '/redfish/v1/Systems/1' }]
        })

    @app.route('/redfish/v1/Systems/1', methods=['GET'])
    def redfish_system():
        try:
            power_state = get_vm_power_state()
            return jsonify({
                "@odata.context": "/redfish/v1/$metadata#ComputerSystem.ComputerSystem",
                "@odata.id": "/redfish/v1/Systems/1",
                "@odata.type": "#ComputerSystem.v1_4_0.ComputerSystem",
                "Id": "1",
                "Name": "System",
                "SystemType": "Physical",
                "PowerState": power_state,
                "Boot": {
                    "BootSourceOverrideTarget": "None",
                    "BootSourceOverrideEnabled": "Continuous",
                    "BootSourceOverrideMode": "Legacy",
                    "BootSourceOverrideSupported": ["Hdd", "Cd"]
                },
                "Actions": {
                    "#ComputerSystem.Reset": {
                        "target": "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
                        "ResetType@Redfish.AllowableValues": [
                            "On", "ForceOff", "GracefulShutdown", "ForceRestart", "GracefulRestart"
                        ]
                    }
                }
            })
        except Exception as e:
            return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': str(e) } }), 500

    @app.route('/redfish/v1/Systems/1/Actions/ComputerSystem.Reset', methods=['POST'])
    def redfish_reset():
        try:
            data = request.get_json()
            reset_type = data.get('ResetType')
            action = {
                'On': 'start',
                'ForceOff': 'stop',
                'GracefulShutdown': 'stop',
                'ForceRestart': 'reset',
                'GracefulRestart': 'reset',
                'PowerReboot': 'reset'
            }.get(reset_type)

            if not action:
                return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': 'Invalid ResetType' } }), 400

            call_vsphere_api(action)

            return jsonify({
                '@odata.id': '/redfish/v1/Systems/1/Actions/ComputerSystem.Reset',
                'ResetType': reset_type
            })

        except Exception as e:
            return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': str(e) } }), 500

    @app.route('/redfish/v1/Managers', methods=['GET'])
    def redfish_managers():
        return jsonify({
            '@odata.context': '/redfish/v1/$metadata#ManagerCollection.ManagerCollection',
            '@odata.id': '/redfish/v1/Managers',
            '@odata.type': '#ManagerCollection.v1_0_0.ManagerCollection',
            'Name': 'Manager Collection',
            'Members@odata.count': 1,
            'Members': [{ '@odata.id': '/redfish/v1/Managers/1' }]
        })

    @app.route('/redfish/v1/Managers/1', methods=['GET'])
    def redfish_manager():
        return jsonify({
            '@odata.context': '/redfish/v1/$metadata#Manager.Manager',
            '@odata.id': '/redfish/v1/Managers/1',
            '@odata.type': '#Manager.v1_3_0.Manager',
            'Id': '1',
            'Name': 'iLO Proxy Manager',
            'ManagerType': 'Service',
            'FirmwareVersion': '1.0',
            'VirtualMedia': { '@odata.id': '/redfish/v1/Managers/1/VirtualMedia' }
        })

    @app.route('/redfish/v1/Managers/1/VirtualMedia', methods=['GET'])
    def redfish_virtual_media_collection():
        return jsonify({
            '@odata.context': '/redfish/v1/$metadata#VirtualMediaCollection.VirtualMediaCollection',
            '@odata.id': '/redfish/v1/Managers/1/VirtualMedia',
            '@odata.type': '#VirtualMediaCollection.VirtualMediaCollection',
            'Name': 'Virtual Media Collection',
            'Members@odata.count': 1,
            'Members': [{ '@odata.id': '/redfish/v1/Managers/1/VirtualMedia/CD', 'MediaTypes': ['CD'] }]
        })

    @app.route('/redfish/v1/Managers/1/VirtualMedia/CD', methods=['GET'])
    def redfish_virtual_media_cd():
        try:
            client = create_client()
            cdrom_svc = client.vcenter.vm.hardware.Cdrom
            cdroms = cdrom_svc.list(vm=vm_id)
            if not cdroms:
                raise Exception("No CD-ROM device found")
            cdrom = cdrom_svc.get(vm=vm_id, cdrom=cdroms[0].cdrom)
            iso_path = cdrom.backing.iso_file if cdrom.backing.type == Cdrom.BackingType.ISO_FILE else None
            inserted = cdrom.state == 'CONNECTED'
            return jsonify({
                '@odata.context': '/redfish/v1/$metadata#VirtualMedia.VirtualMedia',
                '@odata.id': '/redfish/v1/Managers/1/VirtualMedia/CD',
                '@odata.type': '#VirtualMedia.v1_2_0.VirtualMedia',
                'Id': 'CD',
                'Name': 'CD Drive',
                'MediaTypes': ['CD'],
                'Image': iso_path,
                'Inserted': inserted,
                'WriteProtected': True,
                'Actions': {
                    '#VirtualMedia.InsertMedia': {
                        'target': '/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia'
                    },
                    '#VirtualMedia.EjectMedia': {
                        'target': '/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.EjectMedia'
                    }
                }
            })
        except Exception as e:
            return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': str(e) } }), 500

    @app.route('/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia', methods=['POST'])
    def redfish_insert_media():
        try:
            data = request.get_json()
            iso_path = data.get('Image')
            if not iso_path:
                return jsonify({ 'error': { 'code': 'Base.1.0.PropertyMissing', 'message': 'Missing Image field' } }), 400
            client = create_client()
            cdrom_svc = client.vcenter.vm.hardware.Cdrom
            cdroms = cdrom_svc.list(vm=vm_id)
            if not cdroms:
                raise Exception("No CD-ROM device found")
            cdrom_id = cdroms[0].cdrom
            cdrom_svc.update(
                vm=vm_id,
                cdrom=cdrom_id,
                spec=Cdrom.UpdateSpec(
                    backing=Cdrom.BackingSpec(
                        type=Cdrom.BackingType.ISO_FILE,
                        iso_file=iso_path
                    ),
                    start_connected=True,
                    allow_guest_control=False
                )
            )
            cdrom_svc.connect(vm=vm_id, cdrom=cdrom_id)
            return jsonify({ 'Inserted': True, 'Image': iso_path })
        except Exception as e:
            return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': str(e) } }), 500

    @app.route('/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.EjectMedia', methods=['POST'])
    def redfish_eject_media():
        try:
            client = create_client()
            cdrom_svc = client.vcenter.vm.hardware.Cdrom
            cdroms = cdrom_svc.list(vm=vm_id)
            if not cdroms:
                raise Exception("No CD-ROM device found")
            cdrom_id = cdroms[0].cdrom
            auto_answer_vm_question()
            cdrom_svc.update(
                vm=vm_id,
                cdrom=cdrom_id,
                spec=Cdrom.UpdateSpec(
                    backing=Cdrom.BackingSpec(type=Cdrom.BackingType.CLIENT_DEVICE)
                )
            )
            return jsonify({ 'Inserted': False, 'Image': None })
        except Exception as e:
            return jsonify({ 'error': { 'code': 'Base.1.0.GeneralError', 'message': str(e) } }), 500

    @app.route('/redfish/v1/Systems/1', methods=['PATCH'])
    def patch_redfish_system():
        try:
            data = request.get_json()
            boot = data.get('Boot', {})
            target = boot.get('BootSourceOverrideTarget')
            enabled = boot.get('BootSourceOverrideEnabled')

            if not target or target.lower() not in ['cd', 'cdrom', 'hdd']:
                return jsonify({'error': {
                    'code': 'Base.1.0.GeneralError',
                    'message': 'Unsupported or missing BootSourceOverrideTarget'
                }}), 400

            if not enabled or enabled.lower() != 'continuous':
                return jsonify({'error': {
                    'code': 'Base.1.0.GeneralError',
                    'message': 'Only BootSourceOverrideEnabled=Continuous is supported'
                }}), 400

            auth = request.headers.get("Authorization")
            if not auth or not auth.lower().startswith("basic "):
                raise ValueError("Missing or invalid Authorization header")
            try:
                import base64
                auth_decoded = base64.b64decode(auth.split(" ")[1]).decode("utf-8")
                username, password = auth_decoded.split(":", 1)
            except Exception:
                raise ValueError("Invalid Basic Auth format")

            context = pyvmomi_ssl._create_unverified_context()
            si = SmartConnect(
                host=global_config['host'],
                user=username,
                pwd=password,
                sslContext=context
            )

            content = si.RetrieveContent()
            vm = None
            for dc in content.rootFolder.childEntity:
                for entity in dc.vmFolder.childEntity:
                    if isinstance(entity, vim.VirtualMachine) and entity._moId == vm_id:
                        vm = entity
                        break

            if not vm:
                raise Exception("VM not found")

            boot_devices = []
            if target.lower() in ['cd', 'cdrom']:
                boot_devices.append(vim.vm.BootOptions.BootableCdromDevice())
            else:  # hdd
                for device in vm.config.hardware.device:
                    if isinstance(device, vim.vm.device.VirtualDisk):
                        boot_devices.append(vim.vm.BootOptions.BootableDiskDevice(deviceKey=device.key))
                        break

            if not boot_devices:
                raise Exception(f"No {target} device found for boot")

            boot_options = vim.vm.BootOptions(
                bootOrder=boot_devices,
                enterBIOSSetup=False
            )

            config_spec = vim.vm.ConfigSpec(bootOptions=boot_options)
            task = vm.ReconfigVM_Task(spec=config_spec)

            while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
                time.sleep(1)

            if task.info.state == vim.TaskInfo.State.error:
                raise Exception(f"Error in task: {task.info.error.msg}")

            return '', 204

        except Exception as e:
            return jsonify({'error': {
                'code': 'Base.1.0.GeneralError',
                'message': str(e)
            }}), 500
        finally:
            try:
                Disconnect(si)
            except:
                pass

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            'error': {
                'code': 'Base.1.0.GeneralError',
                'message': f'Endpoint {request.method} {request.url} not implemented'
            }
        }), 404

    @app.errorhandler(ValueError)
    def handle_auth_error(e):
        return jsonify({
            'error': {
                'code': 'Base.1.0.AuthenticationError',
                'message': str(e)
            }
        }), 401

    return app
