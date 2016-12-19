class FastHash:
    """A class to calculate fast hash for strings of a given constant length
    x_i = t_i*R^(M-1) + t_(i+1)*R^(M-2) + ... + t_(i+M-1)*R^0 (mod Q)"""

    def __init__(self, string_size):
        self.M = string_size
        self.R = 256
        self.Q = 179424673  # big prime number
        self.multipliers = []
        for i in reversed(xrange(self.M)):
            self.multipliers.append((self.R**i)%self.Q)

    def compute_hash(self, s, start_index = 0):
        if (len(s) - start_index) < self.M:
            print("String length not equal to required length of %d" % self.M)
            return -1
        hash_value = 0
        for i in xrange(self.M):
            hash_value = (hash_value + (ord(s[i+start_index])*self.multipliers[i])%self.Q)%self.Q
        return hash_value

    def extend_hash(self, s, start_index=0, prev_hash=-1):
        if start_index == 0:
            return self.compute_hash(s, start_index)
        if (len(s) - start_index) < self.M:
            print("String length not equal to required length of %d" % self.M)
            return -1
        hash_value = ((prev_hash - ord(s[start_index-1])*self.multipliers[0])*self.R + ord(s[start_index + self.M - 1]))%self.Q
        return hash_value
