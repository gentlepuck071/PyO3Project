
import warnings
warnings.filterwarnings("ignore")
import commune as c

class CLI(c.Module):
    """
    Create and init the CLI class, which handles the coldkey, hotkey and tao transfer 
    """
    # 
    def __init__(
            self,
            config: c.Config = None,

        ) :
        c.new_event_loop(True)
        self.module = c.Module()
        args, kwargs = self.parse_args()
        
        module_list = c.modules()

        fn = None
        module = None
        if len(args) == 0:
            result = c.schema()
        elif len(args)> 0:
            functions = list(set(self.module.functions()  + self.module.get_attributes()))
            args[0] = self.resolve_shortcut(args[0])
            
            # is it a fucntion, assume it is for the module
            if args[0] in functions:
                module = c.Module
                fn = args.pop(0)
            else:
                module_list = c.modules()
                if args[0] in module_list:
                    module = args.pop(0)
                    module = c.module(module)
                else:
                    # is it a server
                    namespace = self.namespace(update=False)
                    if args[0] in namespace:
                        module = args.pop(0)
                        module = c.connect(module)

                    else: 
                        raise Exception(f'No module, function or server found for {args[0]}')
            
            if fn == None:
                if len(args) == 0:
                    fn = "__init__"
                else: 
                    fn = args.pop(0)
                    
                    
            if fn != '__init__':
                fn_name = fn
                fn = getattr(module, fn_name)
                
                
                # if c.is_property(fn):
                #     result = getattr(module(), fn.__name__)
                
                if callable(fn) :
                    if c.classify_method(fn) == 'self':
                        module_inst = module()
                        fn = getattr(module_inst, fn_name)
                elif c.is_property(fn):
                    result =  getattr(module(), fn_name)
                else: 
                    result = fn    
                
            else:
                fn = module
                
            
            if callable(fn):
                result = fn(*args, **kwargs)
                
        else:
            raise Exception ('No module, function or server found for {args[0]}')

        x = result
        if not isinstance(result, type(None)):
            c.print(result)
            
        