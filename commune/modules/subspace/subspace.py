
import torch
import scalecodec
from retry import retry
from typing import List, Dict, Union, Optional, Tuple
from substrateinterface import SubstrateInterface
import commune as c
from typing import List, Dict, Union, Optional, Tuple
from commune.utils.network import ip_to_int, int_to_ip
from rich.prompt import Confirm
from commune.modules.subspace.balance import Balance
from commune.modules.subspace.utils import (U16_NORMALIZED_FLOAT,
                                    U64_MAX,
                                    NANOPERTOKEN, 
                                    U16_MAX, 
                                    is_valid_address_or_public_key, 
                                    )
from commune.modules.subspace.chain_data import (ModuleInfo, 
                                         SubnetInfo, 
                                         custom_rpc_type_registry)
from commune.modules.subspace.errors import (ChainConnectionError,
                                     ChainTransactionError, 
                                     ChainQueryError, StakeError,
                                     UnstakeError, 
                                     TransferError,
                                     RegistrationError, 
                                     SubspaceError)
import streamlit as st
import json
from loguru import logger
import os
logger = logger.opt(colors=True)



class Subspace(c.Module):
    """
    Handles interactions with the subspace chain.
    """
    default_config = c.get_config('subspace', to_munch=False)
    token_decimals = default_config['token_decimals']
    retry_params = default_config['retry_params']
    network2url = default_config['network2url']
    chain = default_config['chain']
    network = default_config['network']
    url = network2url[network]
    subnet = default_config['subnet']
    chain_path = eval(default_config['chain_path'])
    chain_release_path = eval(default_config['chain_release_path'])
    spec_path = eval(default_config['spec_path'])
    key_types = default_config['key_types']
    supported_schemas = default_config['supported_schemas']
    default_netuid = default_config['default_netuid']
    key = default_config['key']
    state = {}

    
    def __init__( 
        self, 
        config = None,
        **kwargs,
    ):
        config = self.set_config(config=config,kwargs=kwargs)
        # self.set_network( config.network)
    @classmethod
    def get_network_url(cls, network:str = network) -> str:
        assert isinstance(network, str), f'network must be a string, not {type(network)}'
        return cls.network2url.get(network)
    @classmethod
    def url2network(cls, url:str) -> str:
        return {v: k for k, v in cls.network2url.items()}.get(url, None)
    
    @classmethod
    def resolve_network_url(cls, network:str , prefix='ws://'):    
        url = cls.get_network_url(network)

        if not url.startswith(prefix):
            url = prefix + url
        
        return url
    def set_network(self, 
                network:str,
                websocket:str=None, 
                ss58_format:int=42, 
                type_registry:dict=custom_rpc_type_registry, 
                type_registry_preset=None, 
                cache_region=None, 
                runtime_config=None, 
                use_remote_preset=False,
                ws_options=None, 
                auto_discover=True, 
                auto_reconnect=True, 
                verbose:bool=True,
                *args, 
                **kwargs):

        '''
        A specialized class in interfacing with a Substrate node.

        Parameters
       A specialized class in interfacing with a Substrate node.

        Parameters
        url : the URL to the substrate node, either in format <https://127.0.0.1:9933> or wss://127.0.0.1:9944
        
        ss58_format : The address type which account IDs will be SS58-encoded to Substrate addresses. Defaults to 42, for Kusama the address type is 2
        
        type_registry : A dict containing the custom type registry in format: {'types': {'customType': 'u32'},..}
        
        type_registry_preset : The name of the predefined type registry shipped with the SCALE-codec, e.g. kusama
        
        cache_region : a Dogpile cache region as a central store for the metadata cache
        
        use_remote_preset : When True preset is downloaded from Github master, otherwise use files from local installed scalecodec package
        
        ws_options : dict of options to pass to the websocket-client create_connection function
        : dict of options to pass to the websocket-client create_connection function
                
        '''

        from substrateinterface import SubstrateInterface
        
        if network == None:
            network = self.network
        self.network = network
        url = self.resolve_network_url(network)
        
        self.url = self.chain_endpoint = url
        

        self.substrate= SubstrateInterface(
                                    url=url, 
                                    websocket=websocket, 
                                    ss58_format=ss58_format, 
                                    type_registry=type_registry, 
                                    type_registry_preset=type_registry_preset, 
                                    cache_region=cache_region, 
                                    runtime_config=runtime_config, 
                                    use_remote_preset=use_remote_preset,
                                    ws_options=ws_options, 
                                    auto_discover=auto_discover, 
                                    auto_reconnect=auto_reconnect, 
                                    *args,
                                    **kwargs)
        if verbose:
            c.print(f'Connected to {network}: {url}...')
        
    def __repr__(self) -> str:
        return f'<Subspace: network={self.network}, url={self.url}>'
    def __str__(self) -> str:
        return f'<Subspace: network={self.network}, url={self.url}>'
    
    
    cache = {}
    def auth(self,
             module:str = None, 
             fn:str = None,
             args: list = None,
             kwargs: dict = None,
             key:str = key,
             network:str=network, netuid = None,
             include_ip:str = True,
             ):
        netuid = self.resolve_netuid(netuid)
    
        key = self.resolve_key(key)
        data = {
            'network': network,
            'subnet': netuid,
            'module': module,
            'fn': fn,
            'args': args,
            'kwargs': kwargs,
            'timestamp': int(c.time()),
            'block': self.block, 
            
        }
        if include_ip:
            ip = c.ip()
            if 'ip' in self.cache:
                external_ip = self.cache.get('ip', ip)
                self.cache['ip'] = ip
            data['ip'] = ip
       
        # data = c.python2str(data)
        auth =  {
            'address': key.ss58_address,
            'signature': key.sign(data).hex(),
            'public_key': key.public_key.hex(),
            'data': data,
        }
        
     
        return auth
    
    def verify(self, 
               auth,
               max_staleness=100,
               ensure_registered=True,):
        key = c.module('key')(ss58_address=auth['address'])
        verified =  key.verify(auth['data'], bytes.fromhex(auth['signature']), bytes.fromhex(auth['public_key']))
        if not verified:
            return {'verified': False, 'error': 'Signature is invalid.'}
        if auth['address'] != key.ss58_address:
            return {'verified': False, 'error': 'Signature address does not match.'}
        
        data = c.jload(auth['data'])
        
        if data['timestamp'] < c.time() - max_staleness:
            return {'verified': False, 'error': 'Signature is stale.', 'timestamp': data['timestamp'], 'now': c.time()}
        if not self.is_registered(key,netuid= data['netuid']) and ensure_registered:
            return {'verified': False, 'error': 'Key is not registered.'}
        return {'verified': True, 'error': None}
    
    #####################
    #### Set Weights ####
    #####################
    def set_weights(
        self,
        key: 'c.key' = None,
        uids: Union[torch.LongTensor, list] = None,
        weights: Union[torch.FloatTensor, list] = None,
        netuid: int = None,
        wait_for_inclusion:bool = True,
        wait_for_finalization:bool = True,
        network = None,
    ) -> bool:
        network = self.resolve_network(network)
        key = self.resolve_key(key)
        netuid = self.resolve_netuid(netuid)
        if uids is None:
            uids = self.uids()
        if weights is None:
            weights = torch.tensor([1 for _ in uids])
            weights = weights / weights.sum()
        weights = weights * U16_MAX
        c.print(f'Weights: {weights}')
        weights = weights.tolist()
        c.print(f'Setting weights for {len(uids)} uids..., {len(weights)}')
        # First convert types.

        with self.substrate as substrate:
            call = substrate.compose_call(
                call_module='SubspaceModule',
                call_function='set_weights',
                call_params = {
                    'uids': uids,
                    'weights': weights,
                    'netuid': netuid,
                }
            )
        # Period dictates how long the extrinsic will stay as part of waiting pool
        extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key, era={'period':100})
        response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion,
                                              wait_for_finalization = wait_for_finalization )
        # We only wait here if we expect finalization.
        if not wait_for_finalization and not wait_for_inclusion:
            c.print(":white_heavy_check_mark: [green]Sent[/green]")
            return True
        response.process_events()
        if response.is_success:
            c.print(":white_heavy_check_mark: [green]Finalized[/green]")            
            c.print(f"Set weights:\n[bold white]  weights: {weights}\n  uids: {uids}[/bold white ]")
            return True
        else:
            c.print(":cross_mark: [red]Failed[/red]: error:{}".format(response.error_message))
            c.print(  'Set weights <red>Failed: </red>' + str(response.error_message) )
            return False

    vote = set_weights

    @classmethod
    def get_key(cls, uri= None) -> 'c.Key':
        
        key = c.module('key')
        if uri != None:
            key = key.create_from_uri(uri)
        else:
            raise NotImplementedError('No uri, mnemonic, privatekey or publickey provided')
        return key
    def get_netuid_for_subnet(self, network: str = None) -> int:
        netuid = self.subnet_namespace.get(network, None)
        return netuid
    
    
    def register(
        self,
        module:str ,  
        tag:str = None,
        stake : int = 0,
        name: str = None, # defaults to module::tag
        address: str = None,
        subnet: str = subnet,
        key : str  = None,
        wait_for_inclusion: bool = False,
        wait_for_finalization: bool = True,
        prompt: bool = False,
        max_allowed_attempts: int = 3,
        update_interval: Optional[int] = None,
        log_verbose: bool = False,
        kwargs : dict = None,
        tag_seperator: str = "::", 
        network: str = None,

    ) -> bool:
        
        network = self.resolve_network(network)
        
        if kwargs is None:
            kwargs = {}
            
        if tag_seperator in module:
            module, tag = module.split(tag_seperator)
            

        name = c.resolve_server_name(module=module, name=name, tag=tag)
        key = key or name
        key = self.resolve_key(key)
            
        address = c.free_address()
        c.serve(module=module, address=address, name=name, kwargs=kwargs)

        netuid = self.get_netuid_for_subnet(subnet)

        if self.is_registered(key):
            return self.update_module(key=key, 
                               name=name, 
                               address=address,
                               netuid=netuid, 
                               )
            
        # netuid = self.subnet_namespace(network)
        if address is None:
            address = f'{c.ip()}:{c.free_port()}'
    
        # Attempt rolling registration.
        call_params = { 
                    'network': subnet.encode('utf-8'),
                    'address': address.encode('utf-8'),
                    'name': name.encode('utf-8'),
                    'stake': stake,
                } 
        c.print(f":satellite: Registering {key} \n Params : ", call_params)

        with self.substrate as substrate:
            
            # create extrinsic call
            call = substrate.compose_call( 
                call_module='SubspaceModule',  
                call_function='register', 
                call_params=call_params
            )
            extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key  )
            response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion=wait_for_inclusion, wait_for_finalization=wait_for_finalization )
            
            # process if registration successful, try again if pow is still valid
            response.process_events()
            
            if response.is_success:
                c.print(":white_heavy_check_mark: [green]Success[/green]")
                return {'success': True, 'message': 'Successfully registered module {} with address {}'.format(name, address)}
            else:
                return {'success': False, 'message': response.error_message}
    
            


    ##################
    #### Transfer ####
    ##################
    def transfer(
        self,
        dest: str, 
        amount: float , 
        key: str =  None,
        wait_for_inclusion: bool = True,
        wait_for_finalization: bool = False,
        prompt: bool = False,
        keep_alive: bool = True,
        network : str = None,
    ) -> bool:
        key = c.get_key(key)
        network = self.resolve_network(network)


        # Validate destination address.
        if not is_valid_address_or_public_key( dest ):
            c.print(":cross_mark: [red]Invalid destination address[/red]:[bold white]\n  {}[/bold white]".format(dest))
            return False

        if isinstance( dest, bytes):
            # Convert bytes to hex string.
            dest = "0x" + dest.hex()


        # Check balance.
        with c.status(":satellite: Checking Balance..."):
            account_balance = self.get_balance( key.ss58_address )
            existential_deposit = self.get_existential_deposit()

        transfer_balance =  Balance.to_nanos(amount)
        with c.status(":satellite: Transferring..."):
            with self.substrate as substrate:
                call = substrate.compose_call(
                    call_module='Balances',
                    call_function='transfer',
                    call_params={
                        'dest': dest, 
                        'value': transfer_balance
                    }
                )

                try:
                    payment_info = substrate.get_payment_info( call = call, keypair = key )
                except Exception as e:
                    c.print(":cross_mark: [red]Failed to get payment info[/red]:[bold white]\n  {}[/bold white]".format(e))
                    payment_info = {
                        'partialFee': 2e7, # assume  0.02 joule 
                    }

                fee = transfer_balance.to_nanos(payment_info['partialFee'])
        
        if not keep_alive:
            # Check if the transfer should keep_alive the account
            existential_deposit = 0

        # Check if we have enough balance.
        if account_balance < (transfer_balance + fee + existential_deposit):
            c.print(":cross_mark: [red]Not enough balance[/red]:[bold white]\n  balance: {}\n  amount: {}\n  for fee: {}[/bold white]".format( account_balance, transfer_balance, fee ))
            return False


        with c.status(":satellite: Transferring to {}"):
            with self.substrate as substrate:
                call = substrate.compose_call(
                    call_module='Balances',
                    call_function='transfer',
                    call_params={
                        'dest': dest, 
                        'value': transfer_balance
                    }
                )

                extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                # We only wait here if we expect finalization.
                if not wait_for_finalization and not wait_for_inclusion:
                    c.print(":white_heavy_check_mark: [green]Sent[/green]")
                    return True

                # Otherwise continue with finalization.
                response.process_events()
                if response.is_success:
                    c.print(":white_heavy_check_mark: [green]Finalized[/green]")
                    block_hash = response.block_hash
                    c.print("[green]Block Hash: {}[/green]".format( block_hash ))
                    new_balance = self.get_balance( key.ss58_address )
                    c.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format(account_balance, new_balance))
                    return {'success': True, 'message': 'Successfully transferred {} to {}'.format(amount, dest)}
                else:
                    c.print(":cross_mark: [red]Failed[/red]: error:{}".format(response.error_message))
                    return {'success': False, 'message': response.error_message}


        
        return False
    
    def get_existential_deposit(
        self,
        block: Optional[int] = None,
        fmt = 'nano'
    ) -> Optional[Balance]:
        """ Returns the existential deposit for the chain. """
        result = self.query_constant(
            module_name='Balances',
            constant_name='ExistentialDeposit',
            block = block,
        )
        
        if result is None:
            return None
        
        return self.format_amount( result.value, fmt = fmt )
        
        
    

        

    #################
    #### Serving ####
    #################
    def update_module (
        self,
        key: str ,
        name: str = None,
        address: str = None,
        netuid: int = None,
        wait_for_inclusion: bool = False,
        wait_for_finalization = True,
        prompt: bool = False,
    ) -> bool:
            
        key = self.resolve_key(key)
        module = self.key2module(key)
        netuid = self.resolve_netuid(netuid)   
        
        if  name == None and address == None:
            c.print(":cross_mark: [red]Invalid arguments[/red]:[bold white]\n  name: {}\n  address: {}\n  netuid: {}[/bold white]".format(name, address, netuid))
            return False     
        if name == None:
            name = ''
        if address == None:
            address = ''
        
        with self.substrate as substrate:
            call_params =  {'address': address,
                            'name': name,
                            'netuid': netuid,
                        }
            c.print(f':satellite: Updating Module: [bold white]{name}[/bold white]',call_params)
            call = substrate.compose_call(
                call_module='SubspaceModule',
                call_function='update_module',
                call_params =call_params
            )
            extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key)
            response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
            if wait_for_inclusion or wait_for_finalization:
                response.process_events()
                if response.is_success:
                    module = self.get_module( key=key, netuid=netuid )
                    c.print(f':white_heavy_check_mark: [green]Updated Module[/green]\n  [bold white]{module}[/bold white]')
                    return True
                else:
                    c.print(f':cross_mark: [green]Failed to Serve module[/green] error: {response.error_message}')
                    return False
            else:
                return True


    def stake(
            self,
            key: Optional[str] ,
            amount: Union[Balance, float] = None, 
            netuid:int = None,
            wait_for_inclusion: bool = True,
            wait_for_finalization: bool = False,
            prompt: bool = False,
            network:str = None,
        ) -> bool:
        network = self.resolve_network(network)
        key = c.get_key(key)
        netuid = self.resolve_netuid(netuid)

        
        # Flag to indicate if we are using the wallet's own hotkey.
        old_balance = self.get_balance( key.ss58_address , fmt='j')
        old_stake = self.get_stake( key.ss58_address , fmt='j')

        if amount is None:
            amount = old_balance
            
        amount = self.to_nano(amount)
        
        c.print(amount)
        # Get current stake

        c.print(f"Old Balance: {old_balance} {amount}")
        with c.status(":satellite: Staking to: [bold white]{}[/bold white] ...".format(self.network)):

            with self.substrate as substrate:
                call = substrate.compose_call(
                call_module='SubspaceModule', 
                call_function='add_stake',
                call_params={
                    'netuid': netuid,
                    'amount_staked': amount
                    }
                )
                extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                response = substrate.submit_extrinsic( extrinsic, 
                                                        wait_for_inclusion = wait_for_inclusion,
                                                        wait_for_finalization = wait_for_finalization )

        if response.is_success:
            c.print(":white_heavy_check_mark: [green]Sent[/green]")
            new_balance = self.get_balance(  key.ss58_address , fmt='j')
            block = self.get_current_block()
            new_stake = self.get_stake(key.ss58_address,block=block, fmt='j') # Get current stake
            c.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_balance, new_balance ))
            c.print("Stake:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_stake, new_stake ))
                
        else:
            c.print(":cross_mark: [red]Stake Error: {}[/red]".format(response.error_message))





    def unstake (
            self,
            key: 'c.Key', 
            amount: float = None, 
            netuid = None,
            wait_for_inclusion:bool = True, 
            wait_for_finalization:bool = False,
            prompt: bool = False,
            network: str= None,
        ) -> bool:
        network = self.resolve_network(network)
        key = c.get_key(key)
        netuid = self.resolve_netuid(netuid)

        old_stake = self.get_stake( key.ss58_address, netuid=netuid, fmt='nano' )
        if amount == None:
            amount = old_stake
            
        amount = self.to_nano(amount)
        old_balance = self.get_balance(  key.ss58_address , fmt='nano')
            
            
        c.print("Unstaking [bold white]{}[/bold white] from [bold white]{}[/bold white]".format(amount, self.network))
        

        with c.status(":satellite: Unstaking from chain: [white]{}[/white] ...".format(self.network)):


            with self.substrate as substrate:
                call = substrate.compose_call(
                call_module='SubspaceModule', 
                call_function='remove_stake',
                call_params={
                    'amount_unstaked': amount,
                    'netuid': netuid
                    }
                )
                extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                # We only wait here if we expect finalization.
                if not wait_for_finalization and not wait_for_inclusion:
                    return True

                response.process_events()


        if response.is_success: # If we successfully unstaked.
            c.print(":white_heavy_check_mark: [green]Finalized[/green]")
            with c.status(":satellite: Checking Balance on: [white]{}[/white] ...".format(self.network)):
                old_balance = self.to_token(old_balance)
                old_stake = self.to_token(old_stake)
                
                new_balance = self.get_balance( key.ss58_address , fmt='token')
                new_stake = self.get_stake( key.ss58_address , fmt='token') # Get stake on hotkey.
                
                c.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_balance, new_balance ))
                c.print("Stake:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_stake, new_stake ))
                return True
        else:
            c.print(":cross_mark: [red]Failed[/red]: Error unknown.")
            return False


    ########################
    #### Standard Calls ####
    ########################

    """ Queries subspace named storage with params and block. """
    @retry(delay=2, tries=3, backoff=2, max_delay=4)
    def query_subspace( self, name: str, block: Optional[int] = None, params: Optional[List[object]] = [], network=None ) -> Optional[object]:
        self.resolve_network(network)
        
        with self.substrate as substrate:
            return substrate.query(
                module='SubspaceModule',
                storage_function = name,
                params = params,
                block_hash = None if block == None else substrate.get_block_hash(block)
                )

    """ Queries subspace map storage with params and block. """
    def query_map( self, name: str, 
                  block: Optional[int] = None, 
                  params: Optional[List[object]] = [default_netuid] ,
                  network:str = None,
                  cache = False,
                  max_age = 60
                  
                  ) -> Optional[object]:

        network = self.resolve_network(network)
        
        with self.substrate as substrate:
            value =  substrate.query_map(
                module='SubspaceModule',
                storage_function = name,
                params = params,
                block_hash = None if block == None else substrate.get_block_hash(block)
            )
        
        return value
        
    
    """ Gets a constant from subspace with module_name, constant_name, and block. """
    def query_constant( self, 
                       module_name: str, 
                       constant_name: str, 
                       block: Optional[int] = None ,
                       network: str = None) -> Optional[object]:
        
        network = self.resolve_network(network)

        with self.substrate as substrate:
            return substrate.get_constant(
                module_name=module_name,
                constant_name=constant_name,
                block_hash = None if block == None else substrate.get_block_hash(block)
            )
      
    #####################################
    #### Hyper parameter calls. ####
    #####################################

    """ Returns network ImmunityPeriod hyper parameter """
    def immunity_period (self, netuid: int = None, block: Optional[int] = None, network :str = None ) -> Optional[int]:
        netuid = self.resolve_netuid( netuid )
        return self.query_subspace("ImmunityPeriod", block, [netuid] ).value


    """ Returns network MinAllowedWeights hyper parameter """
    def min_allowed_weights (self, netuid: int = None, block: Optional[int] = None ) -> Optional[int]:
        netuid = self.resolve_netuid( netuid )
        return self.query_subspace("MinAllowedWeights", block, [netuid] ).value

    """ Returns network MaxWeightsLimit hyper parameter """
    def max_weight_limit (self, netuid: int = None, block: Optional[int] = None ) -> Optional[float]:
        netuid = self.resolve_netuid( netuid )
        return U16_NORMALIZED_FLOAT( self.query_subspace('MaxWeightsLimit', block, [netuid] ).value )

    """ Returns network SubnetN hyper parameter """
    def n (self, netuid: int = None, block: Optional[int] = None ) -> int:
        netuid = self.resolve_netuid( netuid )
        return self.query_subspace('N', block, [netuid] ).value

    """ Returns network MaxAllowedUids hyper parameter """
    def max_allowed_uids (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        netuid = self.resolve_netuid( netuid )
        return self.query_subspace('MaxAllowedUids', block, [netuid] ).value

    """ Returns network Tempo hyper parameter """
    def tempo (self, netuid: int = None, block: Optional[int] = None) -> int:
        netuid = self.resolve_netuid( netuid )
        return self.query_subspace('Tempo', block, [netuid] ).value

    ##########################
    #### Account functions ###
    ##########################
    
    """ Returns network Tempo hyper parameter """
    def subnet_stake(self, netuid: int = None, block: Optional[int] = None, fmt:str='nano') -> int:
        netuid = self.resolve_netuid( netuid )
        return {k.value: self.format_amount(v.value, fmt=fmt) for k,v in self.query_map('Stake', block, [netuid] ).records}

    """ Returns the stake under a coldkey - hotkey pairing """
    
    
    @classmethod
    def resolve_key_ss58(cls, key_ss58):
        
        if isinstance(key_ss58, str):
            if c.key_exists( key_ss58 ):
                key_ss58 = c.get_key( key_ss58 ).ss58_address
        elif hasattr(key_ss58, 'ss58_address'):
            key_ss58 = key_ss58.ss58_address
            
        return key_ss58
    @classmethod
    def resolve_key(cls, key):
        if isinstance(key, str):
            if not c.key_exists( key ):
                c.add_key( key)
            key = c.get_key( key )
        assert hasattr(key, 'ss58_address'), f"Invalid key {key}."
        return key
        
    @classmethod
    def from_nano(cls,x):
        return x / (10**cls.token_decimals)
    to_token = from_nano
    @classmethod
    def to_nano(cls,x):
        return x * (10**cls.token_decimals)
    from_token = to_nano
    @classmethod
    def format_amount(cls, x, fmt='nano'):
        if fmt in ['nano', 'n']:
            return x
        elif fmt in ['token', 'unit', 'j', 'J']:
            return cls.to_token(x)
        else:
            raise ValueError(f"Invalid format {fmt}.")
    
    def get_stake( self, key_ss58: str, block: Optional[int] = None, netuid:int = None , fmt='j' ) -> Optional['Balance']:
        
        key_ss58 = self.resolve_key_ss58( key_ss58 )
        netuid = self.resolve_netuid( netuid )
        return self.format_amount(self.query_subspace( 'Stake', block, [netuid, key_ss58] ).value, fmt=fmt)
       
    ###########################
    #### Global Parameters ####
    ###########################

    @property
    def block (self, network:str=None) -> int:
        return self.get_current_block(network=network)

    def total_stake (self,block: Optional[int] = None ) -> 'Balance':
        return Balance.from_nano( self.query_subspace( "TotalStake", block ).value )


    def loop(self, interval=60):
        while True:
            
            self.save()
            c.sleep(interval)
            
    def save(self, network:str= None):
        network = self.resolve_network(network)
        for netuid in self.netuids():
            state_dict = self.state_dict(network=network, 
                                         save=True, 
                                         load=False,
                                         netuid=netuid)
        self.put(f'archive/{network}/balances', self.balances())

    def load(self, network:str=None, save:bool = False):
        network = self.resolve_network(network)
        state_dict = {}
        for netuid in self.netuids():
            state_dict[netuid] = self.state_dict(network=network, 
                                         save=False, 
                                         load=True,
                                         netuid=netuid)
        return state_dict
    



    cache = {}
    def state_dict(self,
                   key:str = None, # KEY OF THE ATTRIBUTE, NOT A PRIVATE/PUBLIC KEY PAIR
                   netuid: int = 1,
                   network:str= network, 
                   load : bool= False,
                   save : bool = True,
                   max_age: str = 60, 
                   default = None,
                   cache:bool = True) -> dict:
        # network = self.resolve_network(network, ensure_network=False)
        netuid = self.resolve_netuid(netuid)
        subnet = self.netuid2subnet(netuid)
        path = f'archive/{network}/state_{subnet}'
        state_dict = {}
        if load:
            state_dict = self.get(path, default={} ,max_age=max_age, cache=cache)             
        if len(state_dict) == 0:
            if load:
                save = True
                

            state_dict = {
                **self.subnet_state(netuid=netuid),
                'modules': self.modules(netuid=netuid),
                'block': self.block,
                'timestamp': c.timestamp(),
            }
            
            
        if save:
            self.put(path, state_dict, cache=cache)
                   
        state_dict['namespace'] = {m['name']:m['address'] for m in state_dict['modules']}

        return state_dict

    def subnet_states(self, *args, **kwargs):
        subnet_states = {}
        for netuid in self.netuids():
            subnet_state = self.subnet_state(*args,  netuid=netuid, **kwargs)
            subnet_states[subnet_state['name']] = subnet_state
        return subnet_states
            
            
    def subnet_state(self, 
                    include_modules:bool = True,
                    block: Optional[int] = None,
                    netuid=None,
                    network = None) -> list:
        
        network = self.resolve_network(network)
        netuid = self.resolve_netuid(netuid)
        subnet_stake = self.query_subspace( 'SubnetTotalStake', params=[netuid] ).value
        subnet_emission = self.query_subspace( 'SubnetEmission', params=[netuid] ).value
        subnet_founder = self.query_subspace( 'Founder', params=[netuid] ).value
        n = self.query_subspace( 'N', params=[netuid] ).value
        total_stake = self.total_stake()
        subnet = {
                'name': self.netuid2subnet(netuid),
                'netuid': netuid,
                'stake': subnet_stake,
                'emission': subnet_emission,
                'n': n,
                'tempo': self.tempo( netuid = netuid ),
                'immunity_period': self.immunity_period( netuid = netuid ),
                'min_allowed_weights': self.min_allowed_weights( netuid = netuid ),
                'max_allowed_uids': self.max_allowed_uids( netuid = netuid ),
                'ratio': subnet_stake / total_stake,
                'founder': subnet_founder
            }
        return subnet
            
            
        
    docker_compose_path = f'{chain_path}/docker-compose.yml'
    @classmethod
    def get_docker_compose(cls):
        return c.load_yaml(cls.docker_compose_path)
    
    @classmethod
    def start_docker_node(cls, sudo:bool = True, verbose:bool = True):
        cmd = f'docker-compose  -f {cls.docker_compose_path} build '
        return c.cmd(cmd, 
              cwd=cls.chain_path, 
              sudo=sudo,
              verbose=verbose)
    @classmethod
    def save_docker_compose(cls, docker_compose_yaml: dict = None):
        path = f'{cls.chain_path}/docker-compose.yml'
        if docker_compose_yaml is None:
            docker_compose_yaml = cls.get_docker_compose()
        return c.save_yaml(path, docker_compose_yaml)
            

    def get_total_subnets( self, block: Optional[int] = None ) -> int:
        return self.query_subspace( 'TotalSubnets', block ).value      
    
    def get_emission_value_by_subnet( self, netuid: int = None, block: Optional[int] = None ) -> Optional[float]:
        netuid = self.resolve_netuid( netuid )
        return Balance.from_nano( self.query_subspace( 'EmissionValues', block, [ netuid ] ).value )



    def is_registered( self, key: str, netuid: int = None, block: Optional[int] = None) -> bool:
        key_address = self.resolve_key_ss58( key )
        key_addresses = self.keys(netuid=netuid, block=block)
        if key_address in key_addresses:
            return True
        else:
            return False

    def get_uid_for_key_on_subnet( self, key_ss58: str, netuid: int, block: Optional[int] = None) -> int:
        return self.query_subspace( 'Uids', block, [ netuid, key_ss58 ] ).value  


    def get_current_block(self, network=None) -> int:
        r""" Returns the current block number on the chain.
        Returns:
            block_number (int):
                Current chain blocknumber.
        """     
        network = self.resolve_network(network)   
        with self.substrate as substrate:
            return substrate.get_block_number(None)


    def get_balance(self, key: str, block: int = None, fmt='j', network=None) -> Balance:
        r""" Returns the token balance for the passed ss58_address address
        Args:
            address (Substrate address format, default = 42):
                ss58 chain address.
        Return:
            balance (bittensor.utils.balance.Balance):
                account balance
        """
        network = self.resolve_network(network)
        key_ss58 = self.resolve_key_ss58( key )
        
        try:
            @retry(delay=2, tries=3, backoff=2, max_delay=4)
            def make_substrate_call_with_retry():
                with self.substrate as substrate:
                    return substrate.query(
                        module='System',
                        storage_function='Account',
                        params=[key_ss58],
                        block_hash = None if block == None else substrate.get_block_hash( block )
                    )
            result = make_substrate_call_with_retry()
        except scalecodec.exceptions.RemainingScaleBytesNotEmptyException:
            c.critical("Your key it legacy formatted, you need to run btcli stake --ammount 0 to reformat it." )
        return  self.format_amount(result.value['data']['free'] , fmt=fmt)



    balance =  get_balance

    def get_balances(self, block: int = None, fmt:str = 'n', network = None) -> Dict[str, Balance]:
        
        network = self.resolve_network(network)
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.query_map(
                    module='System',
                    storage_function='Account',
                    block_hash = None if block == None else substrate.get_block_hash( block )
                )
        result = make_substrate_call_with_retry()
        return_dict = {}
        for r in result:
            bal = self.format_amount(int( r[1]['data']['free'].value ), fmt=fmt)
            return_dict[r[0].value] = bal
        return return_dict
    balances = get_balances
    
    def resolve_network(self, network: Optional[int] = None, ensure_network:bool = True) -> int:
        
        if ensure_network:
            if not hasattr(self, 'substrate'):
                self.set_network(network)
        if network == None:
            network = self.network
        
        # If network is a string, resolve it to a network id.
        if isinstance(network, str) and network != self.network:
            self.set_network(network)
        return network
    
    def resolve_subnet(self, subnet: Optional[int] = None) -> int:
        if isinstance(subnet, int):
            assert subnet in self.netuids()
            subnet = self.netuid2subnet(netuid=subnet)
        subnets = self.subnets()
        assert subnet in subnets, f"Subnet {subnet} not found in {subnets} for chain {self.chain}"
        return subnet
    

    @staticmethod
    def _null_module() -> ModuleInfo:
        module = ModuleInfo(
            uid = 0,
            netuid = 0,
            active =  0,
            stake = '0',
            rank = 0,
            emission = 0,
            incentive = 0,
            dividends = 0,
            last_update = 0,
            weights = [],
            bonds = [],
            is_null = True,
            key = "000000000000000000000000000000000000000000000000",
        )
        return module


    def subnets(self, detail=False) -> Dict[int, str]:
        subnets = list(self.subnet_namespace.keys())
        if detail:
            subnets = [ self.subnet_state(netuid=subnet) for subnet in subnets]
        return subnets
        

    def netuids(self) -> Dict[int, str]:
        return list(self.subnet_namespace.values())


    
    @property
    def subnet_namespace(self, cache:bool = True, max_age:int=60, network=network ) -> Dict[str, str]:
        
        # Get the namespace for the netuid.
        cache_path = f'archive/{network}/subnet_namespace'
        subnet_namespace = {}
        if cache:
            cached_subnet_namespace = self.get(cache_path, None, max_age= max_age)
            if cached_subnet_namespace != None :
                return cached_subnet_namespace
            
            
        records = self.query_map('SubnetNamespace', params=[]).records
        
        for r in records:
            name = r[0].value
            uid = int(r[1].value)
            subnet_namespace[name] = int(uid)
        
        if cache:
            self.put(cache_path, subnet_namespace)
        return subnet_namespace

    
    @property
    def subnet_reverse_namespace(self ) -> Dict[str, str]:
        
        return {v:k for k,v in self.subnet_namespace.items()}
    
    def netuid2subnet(self, netuid = None):
        subnet_reverse_namespace = self.subnet_reverse_namespace
        if netuid != None:
            return subnet_reverse_namespace.get(netuid, None)
        return subnet_reverse_namespace
    def subnet2netuid(self,subnet:str = None):
        subnet2netuid = self.subnet_namespace
        if subnet != None:
            return subnet2netuid.get(subnet, None)
        return subnet2netuid
        
    def subnet_netuids(self) -> List[int]:
        return list(self.subnet_namespace.values())
    netuids = subnet_netuids

    def resolve_netuid(self, netuid: int = None, subspace_namespace:str=None) -> int:

        
        if isinstance(netuid, str):
            # If the netuid is a subnet name, resolve it to a netuid.
            if subspace_namespace == None:
                subspace_namespace = self.subnet_namespace
            assert netuid in subspace_namespace, f"Subnet {netuid} not found in {subspace_namespace} for chain {self.chain}"
            netuid = subspace_namespace[netuid]
            
        if netuid == None:
            # If the netuid is not specified, use the default.
            netuid = self.default_netuid
            return netuid
        assert isinstance(netuid, int), "netuid must be an integer"
        return netuid


    def key2name(self, key: str = None, netuid: int = None) -> str:
        modules = self.modules(netuid)
        key2name =  { m['key']: m['name']for m in modules}
        if key != None:
            return key2name[key]
            
        
    def name2key(self, name:str=None,  netuid: int = None) -> Dict[str, str]:
        # netuid = self.resolve_netuid(netuid)
             
        modules = self.modules(netuid=netuid)
        
        return { m['name']: m['key'] for m in modules}
        
        
    def namespace(self, netuid: int = None, **kwargs) -> Dict[str, str]:
        
        modules = self.modules(netuid=netuid, **kwargs)
        namespace = { m['name']: m['address'] for m in modules}
        return namespace
    
    
    def name2uid(self, name: str = None, netuid: int = None) -> int:
        
        name2uid = { m['name']: m['uid'] for m in self.modules(netuid=netuid) }
        if name != None:
            return name2uid[name]
        return name2uid
    
    
    def get_module(self, name:str = None, key=None, netuid=None, **kwargs) -> ModuleInfo:
        if key != None:
            module = self.key2module(key=key, netuid=netuid, **kwargs)
        if name != None:
            module = self.name2module(name=name, netuid=netuid, **kwargs)
            
        return module
        
        
    def name2module(self, name:str = None, netuid: int = None, **kwargs) -> ModuleInfo:
        modules = self.modules(netuid=netuid, **kwargs)
        name2module = { m['name']: m for m in modules }
        return name2module[name]
        
        
        
        
        
    def key2module(self, key: str = None, netuid: int = None) -> Dict[str, str]:
        modules = self.modules(netuid=netuid)
        key2module =  { m['key']: m for m in modules }
        
        if key != None:
            key_ss58 = self.resolve_key_ss58(key)
            return key2module[key_ss58]
        return key2module
        
    def module2key(self, module: str = None, netuid: int = None) -> Dict[str, str]:
        modules = self.modules(netuid=netuid)
        module2key =  { m['name']: m['key'] for m in modules }
        
        if module != module:
            return module2key[module]
        return module2key
        
        
    def module_exists(self, module:str, netuid: int = None, **kwargs) -> bool:
        return bool(module in self.namespace(netuid=netuid, **kwargs))
    
    def modules(self,
                netuid: int = default_netuid,
                fmt='nano', 
                detail:bool = True,
                cache:bool = True,
                max_age: int = 60,
                network = network,
                keys = None,
                update = True,
                
                ) -> Dict[str, ModuleInfo]:
        
        
        network = self.resolve_network(network, ensure_network=False)
        netuid = self.resolve_netuid(netuid)
        cache_path = f"archive/{network}.{netuid}/modules"

        if cache:
            modules = self.get(cache_path, default=[], max_age=max_age)

        if len(modules) == 0 :
             
            uid2addresses = { r[0].value: r[1].value for r in self.query_map('Address', params=[netuid]).records}
            uid2key = { r[0].value: r[1].value for r in self.query_map('Keys', params=[netuid]).records}
            uid2name = { r[1].value : r[0].value for r in self.query_map('Namespace', params=[netuid]).records}
            
            emission = self.emission(netuid=netuid)
            incentive = self.incentive(netuid=netuid)
            dividends = self.dividends(netuid=netuid)
            weights = self.weights(netuid=netuid)
            stake = self.subnet_stake(netuid=netuid) # self.stake(netuid=netuid)
            balances = self.balances()
            
            
            
            modules = []
            
            for uid, address in uid2addresses.items():
                key = uid2key[uid]
                module= {
                    'uid': uid,
                    'address': address,
                    'name': uid2name[uid],
                    'key': key,
                    'emission': emission[uid].value,
                    'incentive': incentive[uid].value,
                    'dividends': dividends[uid].value,
                    'stake': stake[ key],
                    'balance': balances[key],
                    'weight': weights[uid] if uid in weights else [],
                    
                }
                modules.append(module)
            
            # if save:
            #     self.put('modules', modules, include_timestamp=True)
            # if detail == False:
            #     modules = [ m['name'] for m in modules.values()]

            for k in ['balance', 'stake', 'emission', 'incentive', 'dividends']:
                for m in modules:
                    m[k] = self.format_amount(m[k], fmt=fmt)


        if keys == None:
            keys = list(modules[0].keys())
        if isinstance(keys, str):
            keys = [keys]
            
        for i, m in enumerate(modules):
            modules[i] ={k: m[k] for k in keys}
            
        if cache or update:
            self.put(cache_path, modules)
                
        return modules
        
    
      
    def names(self, netuid: int = None, **kwargs) -> List[str]:
        return list(self.namespace(netuid=netuid, **kwargs).keys())
       
    def my_modules(self, *args, names_only:bool= True,  **kwargs):
        my_modules = []
        address2key = c.address2key()
        for module in self.modules(*args, **kwargs):
            if module['key'] in address2key:
                my_modules += [module]
        if names_only:
            my_modules = [m['name'] for m in my_modules]
        return my_modules
    
    def my_module_keys(self, *args,  **kwargs):
        modules = self.my_modules(*args, names_only=False, **kwargs)
        return {m['name']: m['key'] for m in modules}
    my_keys = my_module_keys
    def is_my_module(self, name:str):
        return self.name2module(name=name, *args, **kwargs)
    
    def live_keys(self, *args, **kwargs):
        return [m['key'] for m in self.my_modules(*args, **kwargs)]
                

    def key_alive(self, key:str, *args, **kwargs):
        
        return key in self.live_keys(*args, **kwargs)

    @classmethod
    def nodes(cls):
        return c.pm2ls('subspace')
    
    @classmethod
    def kill_nodes(cls):
        for node in cls.nodes():
            c.pm2_kill(node)
    
    @classmethod
    def query(cls, name,  *params,  block=None):
        self = cls()
        return self.query_map(name=name,params=list(params),block=block).records

    @classmethod
    def test(cls, network=subnet):
        subspace = cls()        
        for key_path, key in c.get_keys('test').items():
            port  = c.free_port()
            subspace.register(key=key, 
                              network=network,
                              address=f'{c.external_ip()}:{port}', 
                              name=f'module{key_path}')
        # for key in keys.values():
        #     subspace.set_weights(key=key, netuid=1, weights=[0.5 for n in modules], uids=[n.uid for n in modules])

    @classmethod
    def test_balance(cls):
        self = cls()
        key = cls.get_key('//Alice')
        c.print(self.get_balance(key.ss58_address))
        
        key2 = cls.get_key('//Bob')
        c.print(self.get_balance(key2.ss58_address))
        
        self.transfer(key=key, dest=key2.ss58_address, amount=10)
        
        c.print(self.get_balance(key2.ss58_address))
        
        # c.print(self.query_map('SubnetNamespace', params=[]).records)
    

    chains = ['dev', 'test', 'main']
    @classmethod
    def build(cls, chain:str = 'dev', verbose:bool=False):
        cls.cmd('cargo build --release', cwd=cls.chain_path, verbose=verbose)
        
        for chain in cls.chains:
            c.print(f'CHAIN: {chain}')
            cls.build_spec(chain)    
        

    @classmethod   
    def purge_chain(cls,
                    chain:str = 'dev',
                    user:str = 'alice',
                    base_path:str = None,
                    sudo = False):
        if base_path == None:
            base_path = cls.resolve_chain_base_path(user=user)
        return c.rm(base_path)
    
    
    @classmethod
    def resolve_chain_base_path(cls, user='alice'):
        return cls.resolve_path(f'{user}')

  
    @classmethod
    def build_spec(cls,
                   chain = 'test',
                   raw:bool  = False,
                   disable_default_bootnode = True,

                   ):

        chain_spec = cls.resolve_chain_spec(chain)
        
            
            

        cmd = f'{cls.chain_release_path} build-spec --chain {chain}'
        
        if disable_default_bootnode:
            cmd += ' --disable-default-bootnode'  
        if raw:
            assert c.exists(chain_spec), f'Chain {chain_spec} does not exist.'
            cmd += ' --raw'
            spec_path =chain_spec.replace('.json', '_raw.json')

        cmd += f' > {chain_spec}'
        return c.cmd(f'bash -c "{cmd}"', cwd=cls.chain_path, verbose=True)

    @classmethod
    def chain_specs(cls):
        specs = c.ls(f'{cls.spec_path}/')
        
        return [spec for spec in specs if '_raw' not in spec]
    
    @classmethod
    def chains(cls)-> str:
        return list(cls.chain2spec().keys())   
    
    @classmethod
    def chain2spec(cls, chain = None):
        chain2spec = {os.path.basename(spec).replace('.json', ''): spec for spec in cls.specs()}
        if chain != None: 
            return chain2spec[chain]
        return chain2spec
    
    specs = chain_specs
    @classmethod
    def get_spec(cls, chain:str):
        chain = cls.resolve_chain_spec(chain)
        
        return c.get_json(chain)

    @classmethod
    def spec_exists(cls, chain):
        c.print(c.exists)
        return c.exists(f'{cls.spec_path}/{chain}.json')


    @classmethod
    def resolve_chain_spec(cls, chain = None):
        if chain == None:
            chain = cls.network
        return cls.chain2spec(chain)
        
    @classmethod
    def new_chain_spec(self, 
                       chain,
                       base_chain:str = 'dev', 
                       balances : 'List[str, int]' = None,
                       aura_authorities: 'List[str, int]' = None,
                       grandpa_authorities: 'List[str, int]' = None,
                       ):
        base_spec =  self.get_spec(base_chain)
        new_chain_path = f'{self.spec_path}/{chain}.json'
        
        if balances != None:
            base_spec['balances'] = balances
        if aura_authorities != None:
            base_spec['balances'] = aura_authorities
        c.put_json( new_chain_path, bascse_spec)
        
        return base_spec
    
    new_chain = new_chain_spec

    @classmethod
    def rm_chain(self, chain):
        return c.rm(self.resolve_chain_spec(chain))
    
    @classmethod
    def insert_node_key(cls,
                   node='node01',
                   chain = 'jaketensor_raw.json',
                   suri = 'verify kiss say rigid promote level blue oblige window brave rough duty',
                   key_type = 'gran',
                   scheme = 'Sr25519',
                   password_interactive = False,
                   ):
        
        chain = cls.resolve_chain_spec(chain)
        node_path = f'/tmp/{node}'
        
        if key_type == 'aura':
            schmea = 'Sr25519'
        elif key_type == 'gran':
            schmea = 'Ed25519'
        
        if not c.exists(node_path):
            c.mkdir(node_path)

        cmd = f'{cls.chain_release_path} key insert --base-path {node_path}'
        cmd += f' --suri "{suri}"'
        cmd += f' --scheme {scheme}'
        cmd += f' --chain {chain}'
        assert key_type in cls.key_types, f'key_type ({key_type})must be in {cls.key_types}'
        cmd += f' --key-type {key_type}'
        if password_interactive:
            cmd += ' --password-interactive'
        
        c.print(cmd, color='green')
        return c.cmd(cmd, cwd=cls.chain_path, verbose=True)
    
    @classmethod
    def insert_node_keys(cls,
                   aura_suri : str, 
                   grandpa_suri :str,
                    node='node01',
                   password_interactive = False,
                   ):
        '''
        Insert aura and gran keys for a node
        '''
        cls.insert_node_key(node=node, key_type='aura',  suri=aura_suri)
        cls.insert_node_key(node=node, key_type='gran', suri=grandpa_suri)
       
        return c.cmd(cmd, cwd=cls.chain_path, verbose=True)
    
    
    @classmethod
    def nodes(cls, chain='dev'):
        return c.pm2ls(f'{cls.node_prefix()}::{chain}')

    @classmethod
    def node_prefix(cls):
        return f'{cls.module_path()}.node'
    
    @classmethod
    def st_metrics_dict(cls, x, num_columns=3):
        cols = st.columns(num_columns)
        if self.is_registered:
            neuron = self.neuron
            for i, (k,v) in enumerate(x):
                if type(v) in [int, float]:
                    cols[i % num_columns].metric(label=k, value=v)
                        
       
       
 
    
    @classmethod
    def start_node(cls,

                 chain:int = 'dev',
                 port:int=30333,
                 rpc_port:int=9933,
                 ws_port:int=9945,
                 user : str = 'alice',
                 telemetry_url:str = 'wss://telemetry.polkadot.io/submit/0',
                 validator: bool = True,          
                 boot_nodes : str = None,       
                 purge_chain:bool = True,
                 remote:bool = True,
                 refresh:bool = True,
                 verbose:bool = False,
                 rpc_cors:str = 'all',
                 
                 ):


        cmd = cls.chain_release_path
        port = c.resolve_port(port)
        rpc_port = c.resolve_port(rpc_port)
        ws_port = c.resolve_port(ws_port)
        base_path = cls.resolve_chain_base_path(user=user)
        if purge_chain:
            cls.purge_chain(base_path=base_path)
        
        chain_spec = cls.resolve_chain_spec(chain)
        cmd_kwargs = f' --base-path {base_path}'
        cmd_kwargs += f' --chain {chain_spec}'
        
        if validator :
            cmd_kwargs += ' --validator'
            cmd_kwargs += f' --{user}'
        else:
            cmd_kwargs += ' --ws-external --rpc-external'
        cmd_kwargs += f' --port {port} --rpc-port {rpc_port} --ws-port {ws_port}'
        

            
        if boot_nodes != None:
            cmd_kwargs += f' --bootnodes {boot_nodes}'
            
            
        cmd_kwargs += f' --rpc-cors=all'

        if remote:
            cmd = c.pm2_start(path=cls.chain_release_path, 
                              name=f'{cls.node_prefix()}::{chain}::{user}',
                              cmd_kwargs=cmd_kwargs,
                              refresh=refresh,
                              verbose=verbose)
        else:
            cls.cmd(f'{cmd} {cmd_kwargs}', color='green',verbose=True)
       
    @classmethod
    def release_exists(cls):
        return c.exists(cls.chain_release_path)
       
    @classmethod
    def start_chain(cls, 
                    users = ['alice','bob', 'charlie'] ,
                    chain:str='dev', 
                    verbose:bool = False,
                    reuse_ports : bool = True,
                    sleep :int = 2,
                    build: bool = False,
                    external:bool = True,
                    boot_nodes : str = None,
                    rpc_cors:str = 'all',
                    port_keys: list = ['port','rpc_port','ws_port'],):
        if build:
            cls.build(verbose=verbose)
        avoid_ports = []
        
        ip = c.ip(external=external)
        chain_info_path = f'chain_info.{chain}'
        chain_info = cls.getc(chain_info_path, default={})
        for i, user in enumerate(users):
            

            
            if user in chain_info and reuse_ports:
                node_kwargs = chain_info[user]
                for k in port_keys:
                    node_kwargs[k] = c.resolve_port(node_kwargs[k])
                
            else:
                node_kwargs = {
                               'chain':chain, 
                               'user':user, 
                               'verbose':verbose,
                               'rpc_cors': rpc_cors,
                               'validator': True if bool(i <= len(users)-1) else False,
                               }
                for k in port_keys:
                    port = c.free_port(avoid_ports=avoid_ports)
                    avoid_ports.append(port)
                    node_kwargs[k] = port
            
            node_kwargs['boot_nodes'] = boot_nodes
            chain_info[user] = c.copy(node_kwargs)
            cls.start_node(**chain_info[user])

            cls.sleep(sleep)
            node_id = cls.node_id(chain=chain, user=user)
            boot_nodes = f'/ip4/{ip}/tcp/{node_kwargs["port"]}/p2p/{node_id}'
        cls.putc(chain_info_path, chain_info)


        cls.putc(f'network2url.{chain}', f'{ip}:{node_kwargs["ws_port"]}')
        
       
    @classmethod
    def gen_key(cls, *args, **kwargs):
        return c.module('key').gen(*args, **kwargs)
        
    
    
    key_store_path = '/tmp/subspace/keys'

    @classmethod
    def resolve_node_keystore_path(cls, node):
        path = cls.resolve_path(f'nodes/{node}')
        if not c.exists(path):
            c.mkdir(path)
        return path
    
    @classmethod
    def gen_node_keys(cls, path, **kwargs):
        key_class = c.module('key')
        node_path = f'node.{path}'
        c.print(key_class.add_key(path=f'{node_path}.aura', crypto_type='Sr25519'))
        key_class.add_key(path=f'{node_path}.gran',crypto_type='Ed25519')
        return key_class.keys(node_path, **kwargs)
    
    
    def keys(self, netuid = None, **kwargs):
        netuid = self.resolve_netuid(netuid)
        return [r[1].value for r in self.query_map('Keys', params= [netuid], **kwargs).records]
    
    def registered_keys(self, netuid = None, **kwargs):
        key_addresses = self.keys(netuid=netuid, **kwargs)
        address2key = c.address2key()
        registered_keys = {}
        for k_addr in key_addresses:
            if k_addr in address2key:
                registered_keys[address2key[k_addr]] = k_addr
                
        return registered_keys

    reged = registered_keys
    
    
    

    def query_subnet(self, key, netuid = None, network=None, **kwargs):
        network = self.resolve_network(network)
        netuid = self.resolve_netuid(netuid)
        return self.query_subspace(key, params=[netuid], **kwargs)
    
    def incentive(self, **kwargs):
        return self.query_subnet('Incentive', **kwargs)
        
    def weights(self, netuid = None, **kwargs) -> list:
        netuid = self.resolve_netuid(netuid)
        subnet_weights =  self.query_map('Weights', params=[netuid], **kwargs).records
        weights = {uid.value:list(map(list, w.value)) for uid, w in subnet_weights}
        
        return weights
            
        
        
    
    def emission(self, netuid = None, network=None, **kwargs):
        return self.query_subnet('Emission', netuid=netuid, network=network, **kwargs)
        
    
    def dividends(self, netuid = None, network=None, **kwargs):
        return self.query_subnet('Dividends', netuid=netuid, network=network,  **kwargs)
        
        
    
    
    @classmethod
    def get_node_keys(cls, path):
        for key in cls.gen_node_keys(path):
            c.print(key)
        
    
    @classmethod
    def add_keystore(cls,
                     suri = None ,
                     node = 'alice',
                     chain = 'main',
                     key_type = 'gran',
                     schema = 'Ed25519',
                     password_interactive = False,):
        
        
        if suri is None:
            suri = c.module('key').gen().mnemonic
        base_path = cls.resolve_node_keystore_path(node)
        if key_type == 'gran':
            schema = 'Ed25519'
        elif key_type == 'aura':
            schema = 'Sr25519'
        else:
            raise Exception(f'Unknown key type {key_type}')
        cmd  = f'''
        {cls.chain_release_path} key insert --base-path {base_path}\
        --chain {chain} \
        --scheme {schema} \
        --suri "{suri}" \
        --key-type {key_type}
        '''
        
        if password_interactive:
            cmd = cmd + ' --password-interactive'
        
        return c.cmd(cmd, verbose=True)
        

    
    @classmethod
    def sand(cls, user='Alice'):
        self = cls()
        auth = self.auth(key='alice')
        return self.verify(auth)
        

    def uids(self, netuid = None, **kwargs):
        netuid = self.resolve_netuid(netuid)
        return [v[1].value for v in self.query_map('Uids',None,  [netuid]).records]


    @classmethod
    def node_ids(cls, chain='dev'):
        node_ids = {}
        for node in cls.nodes(chain=chain):
            node_logs = c.logs(node, start_line=100, mode='local')
            for line in node_logs.split('\n'):
                if 'Local node identity is: ' in line:
                    node_ids[node.split('::')[-1]] = line.split('Local node identity is: ')[1].strip()
                    break
                
        return node_ids
    @classmethod
    def node_id(cls, chain='dev', user='alice'):
        return cls.node_ids(chain=chain)[user]
    
    

   
    @classmethod
    def function2streamlit(cls, 
                           fn_schema, 
                           extra_defaults:dict=None,
                           cols:list=None):
        if extra_defaults is None:
            extra_defaults = {}

        st.write('#### Startup Arguments')
        # refresh = st.checkbox('**Refresh**', False)
        # mode = st.selectbox('**Select Mode**', ['pm2',  'ray', 'local'] ) 
        mode = 'pm2'
        serve = True

        kwargs = {}
        fn_schema['default'].pop('self', None)
        fn_schema['default'].pop('cls', None)
        fn_schema['default'].update(extra_defaults)
        
        

        
        
        fn_schema['input'].update({k:str(type(v)).split("'")[1] for k,v in extra_defaults.items()})
        if cols == None:
            cols = [1 for i in list(range(int(len(fn_schema['input'])**0.5)))]
        st.write(f'cols: {cols}')
        cols = st.columns(cols)

        for i, (k,v) in enumerate(fn_schema['input'].items()):
            
            optional = fn_schema['default'][k] != 'NA'
            fn_key = k 
            if k in fn_schema['input']:
                k_type = fn_schema['input'][k]
                if 'Munch' in k_type or 'Dict' in k_type:
                    k_type = 'Dict'
                if k_type.startswith('typing'):
                    k_type = k_type.split('.')[-1]
                fn_key = f'**{k} ({k_type}){"" if optional else "(REQUIRED)"}**'
            col_idx  = i 
            if k in ['kwargs', 'args'] and v == 'NA':
                continue
            

            
            col_idx = col_idx % (len(cols))
            kwargs[k] = cols[col_idx].text_input(fn_key, v)
            
        return kwargs
         
         
         
    @classmethod
    def get_key_info(cls, key):
        
        key_info = {
            'key': key.ss58_address,
            'is_registered': cls.is_registered(key),
        }
        return key_info
         
        
    @classmethod
    def node_help(cls):
        c.cmd(f'{cls.chain_release_path} --help', verbose=True)
        
        
    @classmethod
    def dashboard(cls):
        return c.module('subspace.dashboard').dashboard()
        
  
if __name__ == "__main__":
    Subspace.run()

    