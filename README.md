# Redfish to vSphere Proxy

This application provides a proxy service that translates iLO Redfish API calls to vSphere API calls. It allows managing vSphere VMs through a minimal set of Redfish API calls.

## Features

- Power management (On, Off, Reset)
- Boot order configuration
- Virtual media (CD-ROM) management
- SSL/TLS support
- Multi-VM support through different ports

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ilo-to-vsphere-python
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Generate SSL certificates:
```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -nodes -out certs/server.crt -keyout certs/server.key -days 365
```

## Configuration

Edit the `config.py` file to configure your vSphere environment, this is: set the vSphere hostname and map local ports with each of your virtual machines.

```python
vsphere = {
    'host': 'vsphere-host',
    'vms': [
        {'port': 3000, 'vmId': 'vm-123'},
        {'port': 3001, 'vmId': 'vm-456'}
    ]
}
```

## Usage

Run the application:

```bash
python main.py
```

The proxy will start a separate process for each VM configured in `config.py`, each listening on its specified port. From this moment, you can interact with the server as if you would be interacting with an iLO or any other Redfish compatible management interface.

As an example, an Ansible playbook is provided with some of the most common operations, using the `community.general.redfish_command` module:

1. Power On VM:
```bash
ansible-playbook ilo_operations.yml -i inventory \
                 -e @vault.yaml --ask-vault-password \
                 -e power_on=1
```

2. Set Boot Order to CD-ROM:
```bash
ansible-playbook ilo_operations.yml -i inventory \
                 -e @vault.yaml --ask-vault-password \
                 -e boot_setorder=1 -e boot_device=cd
```

3. Set Boot Order to HDD:
```bash
ansible-playbook ilo_operations.yml -i inventory \
                 -e @vault.yaml --ask-vault-password \
                 -e boot_setorder=1 -e boot_device=hdd
```

4. Reboot VM:
```bash
ansible-playbook ilo_operations.yml -i inventory \
                 -e @vault.yaml --ask-vault-password \
                 -e power_reboot=1
```

## API Endpoints

The proxy implements the following Redfish API endpoints:

- `/redfish/v1` - Service root
- `/redfish/v1/Systems` - System collection
- `/redfish/v1/Systems/1` - System instance
- `/redfish/v1/Managers` - Manager collection
- `/redfish/v1/Managers/1` - Manager instance
- `/redfish/v1/Managers/1/VirtualMedia` - Virtual media collection
- `/redfish/v1/Managers/1/VirtualMedia/CD` - CD-ROM instance
- `/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.EjectMedia` - Eject the CD-ROM
- `/redfish/v1/Managers/1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia` - Mount an ISO

## Authentication

The proxy uses Basic Authentication. Include the Authorization header in your requests:

```
Authorization: Basic <base64-encoded-credentials>
```

These credentials will be sent to vSphere API to authenticate so make sure the user has 
enough permissions in the vSphere instance to make the changes.

## Limitations

1. BootSourceOverrideEnabled only accepts "Continuous" value due to vSphere constrains
2. BootSourceOverrideSupported only allows "HDD" and "CD"
3. Authentication requires vCenter credentials
4. SSL certificates must be in the `certs/` directory

## Security

- SSL certificates should have appropriate permissions (600 for key.pem)
- vCenter credentials are transmitted with each request. They're not cached in any way.

## Troubleshooting

### Common Errors

1. Error 401: Invalid credentials
2. Error 400: 
   - Invalid BootSourceOverrideTarget
   - BootSourceOverrideEnabled is not "Continuous"
3. Error 500: Internal server error
   - Check logs for details
   - Verify vCenter connection
   - Check certificate permissions

### Logs

The proxy logs all requests and responses to the console for debugging purposes. Not suitable for production environments.

## TODO

- Refactor the code to split it in different files
- Implement in some way the `SetOneTimeBoot` function
- Implement properly `ForceOff` and `GracefulShutdown`
- Implement properly `ForceRestart`, `GracefulRestart` and `PowerReboot`


## License

MIT License 
