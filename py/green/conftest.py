import py, os

class Directory(py.test.collect.Directory):
    def collect(self): 
        if os.name == 'nt':
            py.test.skip("Cannot test green layer on windows")
        else:
            return super(Directory, self).run()
